"""
portfolio.py — Bot multi-activo de trend-following diario.

Corre la señal SMA en N activos y reparte el capital equitativamente entre los
que están en tendencia (signal=1). Si ninguno está long, queda en cash. Es la
versión validada en backtest (Exp I, PLAN.md §8): Sharpe 1.14 vs 0.89 del
single-asset, repartiendo el riesgo entre sleeves.

Diseño:
  - Cuenta DEDICADA → los balances reales por activo son el estado (no hace
    falta un store por símbolo). Cada iteración lee la realidad del exchange.
  - Reutiliza la capa segura: orders.py (idempotente, validación), killswitch,
    notifier, journal. La lógica de pesos/rebalanceo es PURA y testeable.
  - Señales con data real (data_client mainnet); ejecución en testnet.

Mainnet sigue bloqueado por config.py.
"""

import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

import pandas as pd

import killswitch
from journal import Journal, EventType
from notifier import Notifier
from orders import OrderRequest, OrderOutcome, send_order
from strategy import sma_signal


class PortfolioExchange(Protocol):
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list: ...
    def fetch_base_balance(self, symbol: str) -> float: ...
    def fetch_quote_balance(self, symbol: str) -> float: ...
    def fetch_price(self, symbol: str) -> float: ...
    def market_filters(self, symbol: str) -> dict: ...
    def create_order(self, symbol, type, side, amount, price=None, params=None) -> dict: ...
    def fetch_order(self, client_order_id, symbol) -> dict: ...


@dataclass(frozen=True)
class PortfolioConfig:
    symbols: tuple = ("BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT")
    fast: int = 20
    slow: int = 50
    timeframe: str = "1d"
    lookback: int = 250
    capital_fraction: float = 0.95   # fracción del equity a desplegar (deja colchón)
    sell_safety: float = 0.999       # margen al vender (precisión/fees)


@dataclass
class PortfolioDeps:
    exchange: PortfolioExchange
    journal: Journal
    notifier: Notifier


# ── Lógica pura ────────────────────────────────────────────────────

def target_weights(signals: dict) -> dict:
    """Equal-weight entre los activos en tendencia (signal=1). Cash si ninguno."""
    longs = [s for s, v in signals.items() if v == 1]
    if not longs:
        return {s: 0.0 for s in signals}
    w = 1.0 / len(longs)
    return {s: (w if signals[s] == 1 else 0.0) for s in signals}


@dataclass
class TradeAction:
    symbol: str
    side: str        # "buy" | "sell"
    qty: float       # cantidad en base


def rebalance_plan(holdings: dict, prices: dict, weights: dict, cash: float,
                   filters: dict, config: PortfolioConfig) -> list:
    """Calcula las órdenes para mover el portfolio hacia los pesos objetivo.

    Pura: recibe estado (holdings, prices, cash) y devuelve TradeActions.
    Ordena ventas primero (liberan cash) y luego compras. Saltea rebalanceos
    por debajo del mínimo operable (evita churn de polvo).
    """
    equity = cash + sum(holdings.get(s, 0.0) * prices[s] for s in weights)
    deployable = equity * config.capital_fraction

    sells, buys = [], []
    for s, w in weights.items():
        price = prices[s]
        if price <= 0:
            continue
        target_qty = (deployable * w) / price
        delta = target_qty - holdings.get(s, 0.0)
        delta_val = abs(delta) * price

        step = filters[s].get("step_size", 0) or 0
        min_notional = filters[s].get("min_notional", 0) or 0
        # Saltear rebalanceos chicos: por debajo del notional mínimo o del step.
        if delta_val < max(min_notional, 1e-9) or abs(delta) < step:
            continue

        if delta > 0:
            buys.append(TradeAction(s, "buy", abs(delta)))
        else:
            sells.append(TradeAction(s, "sell", abs(delta) * config.sell_safety))
    return sells + buys   # ventas primero


# ── Orquestación ───────────────────────────────────────────────────

def _signal_and_price(deps, config, symbol):
    """(signal 0/1, precio) de la última vela CERRADA, o (None, None) sin data."""
    rows = deps.exchange.fetch_ohlcv(symbol, config.timeframe, config.lookback)
    bars = rows[:-1] if len(rows) >= 1 else rows   # descartar la vela en formación
    if len(bars) < config.slow + 1:
        return None, None
    closes = pd.Series([r[4] for r in bars], dtype="float64")
    sig = sma_signal(closes, config.fast, config.slow)
    return int(sig.iloc[-1]), float(closes.iloc[-1])


def run_portfolio_once(deps: PortfolioDeps, config: PortfolioConfig, now_ts: float) -> dict:
    """Una iteración: señales por activo → pesos objetivo → rebalanceo."""
    if killswitch.is_halted():
        return {"action": "halted", "reason": killswitch.halt_reason() or "halt"}

    signals, prices, holdings, filters = {}, {}, {}, {}
    for s in config.symbols:
        sig, price = _signal_and_price(deps, config, s)
        signals[s] = sig if sig is not None else 0      # sin data → no long
        prices[s] = price if price else deps.exchange.fetch_price(s)
        holdings[s] = deps.exchange.fetch_base_balance(s)
        filters[s] = deps.exchange.market_filters(s)

    cash = deps.exchange.fetch_quote_balance(config.symbols[0])
    weights = target_weights(signals)
    plan = rebalance_plan(holdings, prices, weights, cash, filters, config)

    longs = [s for s, v in signals.items() if v == 1]
    deps.journal.log(EventType.SIGNAL, f"portfolio: long={longs}",
                     {"signals": signals, "weights": weights, "n_orders": len(plan)})

    if not plan:
        return {"action": "hold", "longs": longs, "orders": 0}

    bar = int(now_ts // 86400)
    executed = 0
    for a in plan:
        req = OrderRequest(a.symbol, a.side, "market", a.qty,
                           price=prices[a.symbol], intent_id=f"pf-{a.symbol}-{a.side}-{bar}")
        res = send_order(req, deps.exchange)
        deps.journal.log(EventType.ORDER, f"pf {a.side} {a.symbol} → {res.outcome.value}",
                         {"qty": a.qty, "filled": res.filled})
        if res.outcome == OrderOutcome.FILLED:
            executed += 1
            fp = res.average_price or prices[a.symbol]
            if a.side == "buy":
                deps.notifier.entry(a.symbol, res.filled, fp, None)
            else:
                deps.notifier.exit(a.symbol, res.filled, fp, None)
        elif res.outcome == OrderOutcome.UNCERTAIN:
            killswitch.engage_halt(f"pf orden incierta {a.symbol}: {res.reason}")
            deps.journal.log(EventType.HALT, f"pf incierto {a.symbol}")
            deps.notifier.halt(f"Portfolio: orden incierta {a.symbol}")
            return {"action": "uncertain_halt", "symbol": a.symbol}

    return {"action": "rebalanced", "longs": longs, "orders": executed}


def run_forever_portfolio(deps, config, *, sleep_seconds, iterations=None,
                          sleep_fn=time.sleep, now_fn=time.time) -> int:
    count = 0
    while iterations is None or count < iterations:
        try:
            r = run_portfolio_once(deps, config, now_fn())
            deps.journal.log(EventType.INFO, f"pf iteración: {r['action']}")
            print(f"[pf {count + 1}] {r['action']} — long={r.get('longs')} "
                  f"ordenes={r.get('orders', 0)}", flush=True)
        except Exception as e:
            deps.journal.log(EventType.ERROR, f"pf error: {e}")
            deps.notifier.error("portfolio", str(e))
            print(f"[pf {count + 1}] ERROR: {e}", flush=True)
        count += 1
        if iterations is not None and count >= iterations:
            break
        sleep_fn(sleep_seconds)
    return count


def main():
    """Bot multi-activo en testnet. Mainnet bloqueado por config.py."""
    from config import Config
    from exchange import build_exchange, build_public_data_client, CCXTExchange

    Config.validate()
    if not Config.USE_TESTNET:
        print("Mainnet bloqueado. Poné USE_TESTNET=true.", file=sys.stderr)
        sys.exit(1)

    symbols = tuple(os.getenv("PF_SYMBOLS", "BTC/USDT,ETH/USDT,BNB/USDT,SOL/USDT").split(","))
    config = PortfolioConfig(
        symbols=symbols,
        fast=int(os.getenv("FAST", "20")),
        slow=int(os.getenv("SLOW", "50")),
        timeframe=os.getenv("DEFAULT_TIMEFRAME", "1d"),
    )
    exchange = CCXTExchange(build_exchange(Config), symbols[0],
                           data_client=build_public_data_client())
    deps = PortfolioDeps(exchange, Journal(), Notifier.from_env())

    print(f"⚠️  Portfolio trend-following en TESTNET. {list(symbols)} "
          f"SMA {config.fast}/{config.slow} {config.timeframe}.", flush=True)
    deps.journal.log(EventType.INFO, f"portfolio iniciado {symbols}")
    deps.notifier.send(f"🤖 Portfolio trend iniciado en testnet — {list(symbols)}")

    poll = int(os.getenv("POLL_SECONDS", "3600"))
    once = os.getenv("RUN_ONCE", "").lower() in ("1", "true", "yes")
    run_forever_portfolio(deps, config, sleep_seconds=poll, iterations=1 if once else None)


if __name__ == "__main__":
    main()
