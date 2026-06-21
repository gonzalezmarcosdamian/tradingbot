"""
bot.py — Loop principal de orquestación.

Encadena, en cada iteración (ver ARCHITECTURE.md sección 4):

    killswitch → reconciliar → señal → riesgo → orden → estado → journal → alerta

Diseño:
  - `run_once()` es UNA iteración, escrita como orquestación pura sobre
    dependencias inyectadas (exchange, store, journal, notifier, función de
    señal). Así se testea entera con fakes, sin tocar Binance ni la red.
  - Toda la lógica de plata ya vive en módulos probados (risk/orders/state):
    bot.py solo los coordina y traduce señales en intenciones.
  - El kill-switch se consulta SIEMPRE antes de operar. Si la reconciliación
    no es segura, se hace halt y se alerta: ante la duda, no operar.

Limitación conocida (anotada en NEXT_STEPS): el RiskState (circuit breaker
diario) se mantiene en memoria entre iteraciones; un reinicio del proceso lo
resetea. Aceptable para paper trading; persistirlo es trabajo de la etapa 5.
"""

import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Callable, Optional, Protocol

import pandas as pd

import killswitch
from journal import Journal, EventType
from notifier import Notifier
from orders import OrderRequest, OrderOutcome, send_order
from risk import (
    Decision,
    OrderProposal,
    RiskConfig,
    RiskState,
    approve_order,
)
from state import BotState, StateStore, reconcile


# ── Interfaz del exchange que necesita el bot ──────────────────────
# Une lo que piden orders.py (create/fetch/filters/balances) y lo que el loop
# necesita además: velas y balance de quote.

class BotExchange(Protocol):
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list: ...
    def fetch_base_balance(self, symbol: str) -> float: ...
    def fetch_quote_balance(self, symbol: str) -> float: ...
    def market_filters(self, symbol: str) -> dict: ...
    def create_order(self, symbol, type, side, amount, price=None, params=None) -> dict: ...
    def fetch_order(self, client_order_id, symbol) -> dict: ...


# Una función de señal: (closes, fast, slow) -> serie 0/1 (ver strategy.py).
SignalFn = Callable[[pd.Series, int, int], pd.Series]


@dataclass
class BotConfig:
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    fast: int = 20
    slow: int = 50
    lookback: int = 250          # velas a bajar (debe cubrir holgado a `slow`)


@dataclass
class BotDeps:
    exchange: BotExchange
    signal_fn: SignalFn
    store: StateStore
    journal: Journal
    notifier: Notifier


class Action(Enum):
    HALTED = "halted"            # el kill-switch está activo
    UNSAFE_HALT = "unsafe_halt"  # la reconciliación detectó algo y se hizo halt
    NO_DATA = "no_data"          # no hay velas suficientes para la señal
    HOLD = "hold"                # la señal no pide cambios
    ENTERED = "entered"          # se abrió posición
    EXITED = "exited"            # se cerró posición
    REJECTED = "rejected"        # risk.py rechazó la entrada
    UNCERTAIN = "uncertain"      # orden sin confirmar → halt + reconciliar
    ERROR = "error"


@dataclass
class RunResult:
    action: Action
    detail: str = ""
    order_result: object = None


# ── Helpers de la iteración ────────────────────────────────────────

def _closed_bars(rows: list) -> list:
    """Descarta la última vela (en formación) y deja solo las cerradas.

    CCXT suele devolver como última la vela del período en curso. Operar sobre
    ella sería mirar el futuro a medias: usamos solo velas cerradas.
    """
    return rows[:-1] if len(rows) >= 1 else rows


def _latest_signal(deps: BotDeps, config: BotConfig, rows: list):
    """Devuelve (signal_actual:int, last_close:float, bar_id:int) o None si no
    alcanza la data."""
    bars = _closed_bars(rows)
    if len(bars) < config.slow + 1:
        return None
    closes = pd.Series([r[4] for r in bars], dtype="float64")
    signal = deps.signal_fn(closes, config.fast, config.slow)
    return int(signal.iloc[-1]), float(closes.iloc[-1]), int(bars[-1][0])


def _do_entry(
    deps, config, price, bar_id, risk_state, risk_config, today
) -> RunResult:
    """Evalúa y, si risk.py aprueba, ejecuta una entrada a mercado."""
    quote = deps.exchange.fetch_quote_balance(config.symbol)
    base = deps.exchange.fetch_base_balance(config.symbol)
    equity = quote + base * price

    proposal = OrderProposal("buy", available_cash=quote,
                             current_equity=equity, price=price)
    risk_state.position_value = base * price
    decision = approve_order(proposal, risk_state, risk_config, today)
    deps.journal.log(EventType.RISK, f"buy {decision.decision.value}: {decision.reason}",
                     {"reason": decision.reason, "size_quote": decision.size_quote})

    if decision.decision == Decision.REJECTED:
        if "circuit breaker" in decision.reason.lower():
            deps.notifier.circuit_breaker(risk_config.daily_loss_limit)
        return RunResult(Action.REJECTED, decision.reason)

    amount = decision.size_quote / price
    req = OrderRequest(config.symbol, "buy", "market", amount,
                       price=price, intent_id=f"buy-{bar_id}")
    res = send_order(req, deps.exchange)
    return _apply_buy_result(deps, config, res, price, decision, risk_state)


def _apply_buy_result(deps, config, res, price, decision, risk_state) -> RunResult:
    """Traduce el resultado del envío de compra a estado + journal + alerta."""
    deps.journal.log(EventType.ORDER, f"buy → {res.outcome.value}",
                     {"coid": res.client_order_id, "filled": res.filled})

    if res.outcome == OrderOutcome.FILLED:
        fill_price = res.average_price or price
        state = deps.store.load_state()
        state.in_position = True
        state.base_qty = res.filled
        state.avg_entry_price = fill_price
        state.quote_invested = decision.size_quote
        if res.client_order_id not in state.known_orders:
            state.known_orders.append(res.client_order_id)
        deps.store.save_state(state)
        deps.store.record_order(res.client_order_id, "buy", res.filled, fill_price, "filled")
        risk_state.in_position = True
        risk_state.position_value = decision.size_quote
        deps.notifier.entry(config.symbol, res.filled, fill_price, decision.stop_price)
        return RunResult(Action.ENTERED, "posición abierta", res)

    if res.outcome == OrderOutcome.UNCERTAIN:
        return _halt(deps, f"compra sin confirmar: {res.reason}", Action.UNCERTAIN)

    return RunResult(Action.REJECTED, f"compra no ejecutada: {res.reason}", res)


def _do_exit(deps, config, price, bar_id, risk_state, risk_config, today) -> RunResult:
    """Cierra la posición a mercado (la salida normal de la estrategia)."""
    state = deps.store.load_state()
    amount = state.base_qty
    # Sincronizar el RiskState con la posición real antes de aprobar la salida:
    # tras un reinicio el RiskState arranca en cero, pero el estado persistido
    # (ya reconciliado contra el exchange) es la verdad sobre si hay posición.
    risk_state.in_position = True
    risk_state.position_value = amount * price
    proposal = OrderProposal("sell", available_cash=0.0,
                             current_equity=0.0, price=price)
    decision = approve_order(proposal, risk_state, risk_config, today)
    deps.journal.log(EventType.RISK, f"sell {decision.decision.value}: {decision.reason}")

    if decision.decision == Decision.REJECTED:
        return RunResult(Action.REJECTED, decision.reason)

    req = OrderRequest(config.symbol, "sell", "market", amount,
                       price=price, intent_id=f"sell-{bar_id}")
    res = send_order(req, deps.exchange)
    deps.journal.log(EventType.ORDER, f"sell → {res.outcome.value}",
                     {"coid": res.client_order_id, "filled": res.filled})

    if res.outcome == OrderOutcome.FILLED:
        fill_price = res.average_price or price
        pnl = (fill_price - state.avg_entry_price) * res.filled
        pnl_pct = (fill_price / state.avg_entry_price - 1) if state.avg_entry_price else 0.0
        # Registro estructurado del trade cerrado, para que evaluator.py mida.
        deps.journal.log(EventType.ORDER, "trade cerrado",
                         {"closed_trade": True, "entry": state.avg_entry_price,
                          "exit": fill_price, "qty": res.filled,
                          "pnl": pnl, "pnl_pct": pnl_pct})
        deps.store.save_state(BotState(in_position=False, base_qty=0.0,
                                       avg_entry_price=0.0, quote_invested=0.0,
                                       known_orders=state.known_orders))
        deps.store.record_order(res.client_order_id, "sell", res.filled, fill_price, "filled")
        risk_state.in_position = False
        risk_state.position_value = 0.0
        risk_state.realized_pnl_today += pnl
        deps.notifier.exit(config.symbol, res.filled, fill_price, pnl)
        return RunResult(Action.EXITED, "posición cerrada", res)

    if res.outcome == OrderOutcome.UNCERTAIN:
        return _halt(deps, f"venta sin confirmar: {res.reason}", Action.UNCERTAIN)

    return RunResult(Action.REJECTED, f"venta no ejecutada: {res.reason}", res)


def _halt(deps: BotDeps, reason: str, action: Action) -> RunResult:
    """Detiene el bot, lo registra y alerta. Camino común de los abortos."""
    killswitch.engage_halt(reason)
    deps.journal.log(EventType.HALT, reason)
    deps.notifier.halt(reason)
    return RunResult(action, reason)


# ── Una iteración del loop ─────────────────────────────────────────

def run_once(
    deps: BotDeps,
    config: BotConfig,
    risk_state: RiskState,
    risk_config: RiskConfig,
    today: Optional[date] = None,
) -> RunResult:
    """Ejecuta una iteración completa del bot. Pura orquestación: toda la
    lógica sensible vive en los módulos probados que coordina."""
    today = today or date.today()

    # 1. Kill-switch: si está detenido, no se opera (ni se reanuda solo).
    if killswitch.is_halted():
        return RunResult(Action.HALTED, killswitch.halt_reason() or "halt activo")

    # 2. Reconciliación: el exchange manda. Ante discrepancia grave → halt.
    state = deps.store.load_state()
    report = reconcile(state, deps.exchange, config.symbol)
    deps.store.save_state(report.state)
    if report.discrepancies:
        deps.journal.log(EventType.RECONCILE, "discrepancias en reconciliación",
                         {"discrepancies": report.discrepancies})
        # A stdout también: en producción necesitamos ver POR QUÉ reconcilió así.
        for d in report.discrepancies:
            print(f"[reconcile] {d}", flush=True)
    if not report.safe_to_trade:
        return _halt(deps, "reconciliación insegura al arrancar", Action.UNSAFE_HALT)

    # 3. Señal de la última vela cerrada
    rows = deps.exchange.fetch_ohlcv(config.symbol, config.timeframe, config.lookback)
    latest = _latest_signal(deps, config, rows)
    if latest is None:
        return RunResult(Action.NO_DATA, "velas insuficientes para la señal")
    signal, price, bar_id = latest

    want_long = signal == 1
    in_position = report.state.in_position

    # 4. Traducir señal → acción
    if want_long and not in_position:
        return _do_entry(deps, config, price, bar_id, risk_state, risk_config, today)
    if not want_long and in_position:
        return _do_exit(deps, config, price, bar_id, risk_state, risk_config, today)
    return RunResult(Action.HOLD, "sin cambios")


# ── Loop continuo ──────────────────────────────────────────────────

def run_forever(
    deps: BotDeps,
    config: BotConfig,
    risk_state: RiskState,
    risk_config: RiskConfig,
    *,
    sleep_seconds: float,
    iterations: Optional[int] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    today_fn: Callable[[], date] = date.today,
    report_every: int = 0,
) -> int:
    """Corre run_once() en bucle, durmiendo entre iteraciones.

    Robusto a fallos: una excepción en una iteración se registra y alerta, pero
    NO tumba el proceso (la próxima vela puede salir bien; si es algo grave, el
    propio run_once ya habrá hecho halt). `iterations` acota el bucle en tests;
    sleep_fn/today_fn se inyectan para testear sin dormir ni depender del reloj.

    Devuelve la cantidad de iteraciones ejecutadas.
    """
    count = 0
    while iterations is None or count < iterations:
        try:
            result = run_once(deps, config, risk_state, risk_config, today_fn())
            deps.journal.log(EventType.INFO, f"iteración: {result.action.value}",
                             {"detail": result.detail})
            # También a stdout: en producción (Railway) los logs son la ventana
            # principal para ver qué hace el bot sin abrir el journal del volumen.
            print(f"[iter {count + 1}] {result.action.value} — {result.detail}", flush=True)
        except Exception as e:  # red/exchange inestable: seguir vivo, alertar
            deps.journal.log(EventType.ERROR, f"error en iteración: {e}")
            deps.notifier.error("loop", str(e))
            print(f"[iter {count + 1}] ERROR: {e}", flush=True)
        # Reporte periódico de performance a stdout (visible en los logs sin SSH)
        if report_every and (count + 1) % report_every == 0:
            try:
                from evaluator import evaluate, format_report
                print(format_report(evaluate(deps.journal)), flush=True)
            except Exception:
                pass
        count += 1
        if iterations is not None and count >= iterations:
            break
        sleep_fn(sleep_seconds)
    return count


# ── Wiring real para paper trading en testnet ──────────────────────

def main():
    """Arranca el bot en modo paper trading (testnet). Mainnet sigue bloqueado
    por el guard de config.py: este entrypoint NO opera con dinero real.

    MODE=dca delega al Smart DCA (dca.py); por defecto corre la estrategia."""
    if os.getenv("MODE", "strategy").lower() == "dca":
        import dca
        return dca.main()

    from config import Config
    from exchange import build_exchange, CCXTExchange
    from strategy import STRATEGIES

    Config.validate()
    if not Config.USE_TESTNET:
        print("Mainnet bloqueado. Poné USE_TESTNET=true.", file=sys.stderr)
        sys.exit(1)

    print("⚠️  Paper trading en TESTNET (plata falsa). El cruce de medias NO "
          "mostró edge: esto valida la infraestructura, no es una estrategia "
          "rentable. Ver NEXT_STEPS.md.", flush=True)

    strat_name = os.getenv("STRATEGY", "SMA")
    signal_fn = STRATEGIES.get(strat_name, STRATEGIES["SMA"])
    client = build_exchange(Config)
    exchange = CCXTExchange(client, Config.SYMBOL)

    deps = BotDeps(
        exchange=exchange,
        signal_fn=signal_fn,
        store=StateStore(),
        journal=Journal(),
        notifier=Notifier.from_env(),
    )
    config = BotConfig(
        symbol=Config.SYMBOL,
        timeframe=Config.TIMEFRAME,
        fast=int(os.getenv("FAST", "20")),
        slow=int(os.getenv("SLOW", "50")),
    )
    # Una iteración por vela: dormimos lo que dura el timeframe.
    # POLL_SECONDS permite acelerar el ciclo para demos/observabilidad (0 = usar
    # el timeframe). Iterar más rápido que la vela solo repite la misma señal.
    interval = int(os.getenv("POLL_SECONDS", "0")) or client.parse_timeframe(Config.TIMEFRAME)

    deps.journal.log(EventType.INFO,
                     f"bot iniciado (testnet) {config.symbol} {config.timeframe} "
                     f"{strat_name} fast={config.fast} slow={config.slow}")
    deps.notifier.send(f"🤖 Bot iniciado en testnet — {config.symbol} {config.timeframe} "
                       f"({strat_name}). Paper trading.")
    run_forever(deps, config, RiskState(), RiskConfig(), sleep_seconds=interval,
                report_every=int(os.getenv("REPORT_EVERY", "12")))


if __name__ == "__main__":
    main()
