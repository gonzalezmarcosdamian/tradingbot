"""
dca.py — Smart DCA con presupuesto por período y reparto por análisis.

Modelo (ejemplo guía del usuario):
  "100 USDT por mes, 4 compras semanales, pero que ANALICE y reparta el monto
   según el momento: capaz 50/20/10/20 en vez de 25/25/25/25."

Cómo lo logra, SIN predecir dirección ni pasarse del presupuesto:
  - Presupuesto por período (ej. 100 USDT / mes) y N compras (ej. 4 semanales).
  - En cada compra calcula la CUOTA JUSTA = presupuesto_restante / compras_restantes.
    (La última compra del período deploya lo que quede → siempre se usa el 100%.)
  - Inclina esa cuota con un ANÁLISIS del momento (un múltiplo):
      · desvío del precio respecto de su media larga (barato → compra más),
      · RSI (sobrevendido → compra más; sobrecomprado → menos).
    Acotado a [min_mult, max_mult] para no descontrolarse.
  - El monto final se topa con lo que queda del presupuesto y del cash.

Reutiliza la capa segura (orders idempotente, journal, killswitch, notifier).
NO usa risk.py (ese modela una posición con entrada/salida; DCA acumula).
Toda la lógica de decisión es PURA y testeable sin red.
"""

import json
import os
import sys
import time
from dataclasses import dataclass, asdict, replace
from typing import Optional, Protocol

import killswitch
from journal import Journal, EventType
from notifier import Notifier
from orders import OrderRequest, OrderOutcome, send_order


# ── Interfaz del exchange para DCA ─────────────────────────────────

class DCAExchange(Protocol):
    def fetch_price(self, symbol: str) -> float: ...
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list: ...
    def fetch_quote_balance(self, symbol: str) -> float: ...
    def market_filters(self, symbol: str) -> dict: ...
    def create_order(self, symbol, type, side, amount, price=None, params=None) -> dict: ...
    def fetch_order(self, client_order_id, symbol) -> dict: ...
    def fetch_base_balance(self, symbol: str) -> float: ...


@dataclass(frozen=True)
class DCAConfig:
    symbol: str = "BTC/USDT"
    period_budget: float = 100.0       # presupuesto por período (ej. USDT/mes)
    period_seconds: int = 2_592_000    # duración del período (default: 30 días)
    buys_per_period: int = 4           # en cuántas compras se reparte
    min_quote: float = 5.0             # piso por compra (evita polvo < min notional)
    # ── Análisis (el "smart") ──
    smart: bool = True                 # False = reparto parejo (múltiplo 1)
    timeframe: str = "1d"              # timeframe para media y RSI
    ma_period: int = 30                # velas para la media larga
    rsi_period: int = 14
    sensitivity: float = 5.0           # peso del desvío de media en el múltiplo
    rsi_sensitivity: float = 1.0       # peso del RSI en el múltiplo
    min_mult: float = 0.3              # nunca menos que 0.3x la cuota justa
    max_mult: float = 2.5              # nunca más que 2.5x la cuota justa

    @property
    def interval_seconds(self) -> float:
        """Tiempo objetivo entre compras (período / nº de compras)."""
        return self.period_seconds / max(1, self.buys_per_period)


@dataclass
class DCAState:
    period_start_ts: Optional[float] = None
    spent_this_period: float = 0.0
    buys_this_period: int = 0
    last_buy_ts: Optional[float] = None
    total_spent: float = 0.0
    total_buys: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(s: str) -> "DCAState":
        return DCAState(**json.loads(s))


@dataclass
class Analysis:
    price: float
    ma: Optional[float]
    rsi: Optional[float]
    multiplier: float


@dataclass
class DCADecision:
    should_buy: bool
    reason: str
    quote_amount: float = 0.0
    fair_share: float = 0.0
    multiplier: float = 1.0


@dataclass
class DCAResult:
    bought: bool
    reason: str
    quote_amount: float = 0.0
    analysis: Optional[Analysis] = None
    order_result: object = None


# ── Persistencia (JSON en DATA_DIR) ────────────────────────────────

class DCAStore:
    def __init__(self, path: Optional[str] = None):
        if path is None:
            base = os.getenv("DATA_DIR", "./data")
            os.makedirs(base, exist_ok=True)
            path = os.path.join(base, "dca_state.json")
        self.path = path

    def load(self) -> DCAState:
        if not os.path.exists(self.path):
            return DCAState()
        with open(self.path, "r", encoding="utf-8") as f:
            return DCAState.from_json(f.read())

    def save(self, state: DCAState):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(state.to_json())


# ── Análisis (lógica pura) ─────────────────────────────────────────

def simple_ma(closes: list, period: int) -> Optional[float]:
    """Media simple de los últimos `period` cierres. None si no alcanza data."""
    if period <= 0 or len(closes) < period:
        return None
    window = closes[-period:]
    return sum(window) / len(window)


def rsi_last(closes: list, period: int = 14) -> Optional[float]:
    """RSI (último valor) sobre una lista de cierres. None si no alcanza data."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    window = deltas[-period:]
    gains = sum(d for d in window if d > 0) / period
    losses = sum(-d for d in window if d < 0) / period
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


def analyze(closes: list, price: float, config: DCAConfig) -> Analysis:
    """Calcula el múltiplo de reparto a partir del momento de mercado.

    Combina (promedio) dos lecturas, cada una centrada en 1.0:
      - desvío del precio vs su media larga (barato → > 1),
      - RSI (sobrevendido → > 1, sobrecomprado → < 1).
    Acotado a [min_mult, max_mult]. Sin smart o sin data → múltiplo 1.0.
    """
    ma = simple_ma(closes, config.ma_period)
    rsi = rsi_last(closes, config.rsi_period)
    if not config.smart:
        return Analysis(price, ma, rsi, 1.0)

    parts = []
    if ma and ma > 0:
        deviation = (price - ma) / ma            # negativo = barato
        parts.append(1.0 - config.sensitivity * deviation)
    if rsi is not None:
        parts.append(1.0 + config.rsi_sensitivity * ((50.0 - rsi) / 50.0))

    mult = sum(parts) / len(parts) if parts else 1.0
    mult = max(config.min_mult, min(config.max_mult, mult))
    return Analysis(price, ma, rsi, mult)


def maybe_reset_period(state: DCAState, config: DCAConfig, now_ts: float) -> DCAState:
    """Devuelve el estado con el período reiniciado si venció (o si es el 1ro)."""
    if state.period_start_ts is None or now_ts - state.period_start_ts >= config.period_seconds:
        return replace(state, period_start_ts=now_ts, spent_this_period=0.0,
                       buys_this_period=0)
    return state


def decide(config: DCAConfig, state: DCAState, now_ts: float,
           available_cash: float, multiplier: float) -> DCADecision:
    """Decide si compra y cuánto. Pura. Asume el período ya reiniciado si tocaba."""
    # 1. Intervalo entre compras
    if state.last_buy_ts is not None and now_ts - state.last_buy_ts < config.interval_seconds:
        return DCADecision(False, "aún dentro del intervalo entre compras")

    # 2. ¿Quedan compras / presupuesto en el período?
    remaining_buys = config.buys_per_period - state.buys_this_period
    if remaining_buys <= 0:
        return DCADecision(False, "compras del período completas")
    remaining_budget = config.period_budget - state.spent_this_period
    if remaining_budget <= 0:
        return DCADecision(False, "presupuesto del período agotado")

    # 3. Cuota justa e inclinación por análisis
    fair_share = remaining_budget / remaining_buys
    desired = fair_share * multiplier

    # 4. Topes: no pasar el presupuesto restante ni el cash disponible
    upper = min(remaining_budget, available_cash)
    if upper < config.min_quote:
        return DCADecision(False, f"cash/presupuesto insuficiente ({upper:.2f})")
    amount = min(max(desired, config.min_quote), upper)

    return DCADecision(True, f"compra DCA (x{multiplier:.2f})",
                       quote_amount=amount, fair_share=fair_share, multiplier=multiplier)


# ── Orquestación de una compra ─────────────────────────────────────

@dataclass
class DCADeps:
    exchange: DCAExchange
    journal: Journal
    notifier: Notifier


def run_dca_once(deps: DCADeps, config: DCAConfig, store: DCAStore, now_ts: float) -> DCAResult:
    if killswitch.is_halted():
        return DCAResult(False, "halt activo")

    state = maybe_reset_period(store.load(), config, now_ts)
    price = deps.exchange.fetch_price(config.symbol)

    closes = []
    if config.smart:
        rows = deps.exchange.fetch_ohlcv(config.symbol, config.timeframe,
                                         max(config.ma_period, config.rsi_period) + 5)
        closes = [r[4] for r in rows]
    a = analyze(closes, price, config)

    cash = deps.exchange.fetch_quote_balance(config.symbol)
    decision = decide(config, state, now_ts, cash, a.multiplier)
    deps.journal.log(EventType.SIGNAL,
                     f"dca: {decision.reason}",
                     {"price": price, "ma": a.ma, "rsi": a.rsi,
                      "multiplier": a.multiplier, "fair_share": decision.fair_share,
                      "amount": decision.quote_amount})

    if not decision.should_buy:
        return DCAResult(False, decision.reason, analysis=a)

    amount_base = decision.quote_amount / price
    bucket = int(now_ts // config.interval_seconds)  # idempotencia por ventana
    req = OrderRequest(config.symbol, "buy", "market", amount_base,
                       price=price, intent_id=f"dca-{bucket}")
    res = send_order(req, deps.exchange)
    deps.journal.log(EventType.ORDER, f"dca buy → {res.outcome.value}",
                     {"coid": res.client_order_id, "filled": res.filled,
                      "quote": decision.quote_amount})

    if res.outcome == OrderOutcome.FILLED:
        fill_price = res.average_price or price
        state.spent_this_period += decision.quote_amount
        state.buys_this_period += 1
        state.last_buy_ts = now_ts
        state.total_spent += decision.quote_amount
        state.total_buys += 1
        store.save(state)
        deps.notifier.entry(config.symbol, res.filled, fill_price, None)
        return DCAResult(True, "compra ejecutada", decision.quote_amount, a, res)

    if res.outcome == OrderOutcome.UNCERTAIN:
        killswitch.engage_halt(f"dca compra sin confirmar: {res.reason}")
        deps.journal.log(EventType.HALT, "dca: compra incierta → halt")
        deps.notifier.halt("DCA: compra sin confirmar, requiere reconciliación")
        return DCAResult(False, "incierta → halt", decision.quote_amount, a, res)

    return DCAResult(False, f"no ejecutada: {res.reason}", decision.quote_amount, a, res)


# ── Loop continuo ──────────────────────────────────────────────────

def run_forever_dca(deps, config, store, *, sleep_seconds, iterations=None,
                    sleep_fn=time.sleep, now_fn=time.time) -> int:
    """Corre run_dca_once en bucle, robusto a fallos."""
    count = 0
    while iterations is None or count < iterations:
        try:
            res = run_dca_once(deps, config, store, now_fn())
            deps.journal.log(EventType.INFO, f"dca iteración: {res.reason}")
            tag = f"BUY {res.quote_amount:.2f}" if res.bought else "skip"
            print(f"[dca {count + 1}] {tag} — {res.reason}", flush=True)
        except Exception as e:
            deps.journal.log(EventType.ERROR, f"dca error: {e}")
            deps.notifier.error("dca", str(e))
            print(f"[dca {count + 1}] ERROR: {e}", flush=True)
        count += 1
        if iterations is not None and count >= iterations:
            break
        sleep_fn(sleep_seconds)
    return count


# ── Wiring real (testnet) ──────────────────────────────────────────

def main():
    """Arranca el Smart DCA en testnet. Mainnet sigue bloqueado por config.py."""
    from config import Config
    from exchange import build_exchange, CCXTExchange

    Config.validate()
    if not Config.USE_TESTNET:
        print("Mainnet bloqueado. Poné USE_TESTNET=true.", file=sys.stderr)
        sys.exit(1)

    config = DCAConfig(
        symbol=Config.SYMBOL,
        period_budget=float(os.getenv("DCA_PERIOD_BUDGET", "100")),
        period_seconds=int(os.getenv("DCA_PERIOD_SECONDS", "2592000")),
        buys_per_period=int(os.getenv("DCA_BUYS_PER_PERIOD", "4")),
        min_quote=float(os.getenv("DCA_MIN_QUOTE", "5")),
        smart=os.getenv("DCA_SMART", "true").lower() == "true",
        timeframe=os.getenv("DCA_TIMEFRAME", "1d"),
        ma_period=int(os.getenv("DCA_MA_PERIOD", "30")),
        rsi_period=int(os.getenv("DCA_RSI_PERIOD", "14")),
        sensitivity=float(os.getenv("DCA_SENSITIVITY", "5")),
        rsi_sensitivity=float(os.getenv("DCA_RSI_SENSITIVITY", "1")),
        min_mult=float(os.getenv("DCA_MIN_MULT", "0.3")),
        max_mult=float(os.getenv("DCA_MAX_MULT", "2.5")),
    )
    deps = DCADeps(
        exchange=CCXTExchange(build_exchange(Config), Config.SYMBOL),
        journal=Journal(),
        notifier=Notifier.from_env(),
    )
    store = DCAStore()

    print(f"⚠️  Smart DCA en TESTNET (plata falsa). {config.symbol} "
          f"{config.period_budget}/período en {config.buys_per_period} compras, "
          f"smart={config.smart}.", flush=True)
    deps.journal.log(EventType.INFO, "dca iniciado (testnet)")
    deps.notifier.send(f"🤖 Smart DCA iniciado en testnet — {config.symbol}")

    poll = int(os.getenv("POLL_SECONDS", "3600"))
    run_forever_dca(deps, config, store, sleep_seconds=poll)


if __name__ == "__main__":
    main()
