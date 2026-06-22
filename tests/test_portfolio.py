"""
test_portfolio.py — Tests del bot multi-activo.

Cubre la lógica pura (pesos objetivo, plan de rebalanceo) y la orquestación de
una iteración contra un exchange falso multi-símbolo.
"""

import killswitch
from portfolio import (
    PortfolioConfig, PortfolioDeps, TradeAction,
    target_weights, rebalance_plan, run_portfolio_once,
)
from journal import Journal
from notifier import Notifier


# ── Pesos objetivo ─────────────────────────────────────────────────

def test_pesos_equal_weight_entre_long():
    w = target_weights({"BTC/USDT": 1, "ETH/USDT": 1, "SOL/USDT": 0})
    assert w["BTC/USDT"] == 0.5 and w["ETH/USDT"] == 0.5 and w["SOL/USDT"] == 0.0


def test_pesos_todos_cash_si_ninguno_long():
    w = target_weights({"BTC/USDT": 0, "ETH/USDT": 0})
    assert all(v == 0.0 for v in w.values())


def test_pesos_uno_solo_long_lleva_todo():
    w = target_weights({"BTC/USDT": 1, "ETH/USDT": 0, "SOL/USDT": 0})
    assert w["BTC/USDT"] == 1.0


# ── Plan de rebalanceo ─────────────────────────────────────────────

FILT = {"step_size": 0.00001, "min_notional": 10.0, "ref_price": 0}
CFG = PortfolioConfig(symbols=("BTC/USDT", "ETH/USDT"), capital_fraction=1.0)


def _filters(symbols):
    return {s: dict(FILT) for s in symbols}


def test_plan_compra_cuando_entra_en_tendencia():
    # Sin holdings, BTC pasa a long con peso 1.0 → comprar ~todo el cash en BTC
    holdings = {"BTC/USDT": 0.0, "ETH/USDT": 0.0}
    prices = {"BTC/USDT": 100.0, "ETH/USDT": 50.0}
    weights = {"BTC/USDT": 1.0, "ETH/USDT": 0.0}
    plan = rebalance_plan(holdings, prices, weights, cash=1000.0, filters=_filters(CFG.symbols), config=CFG)
    assert len(plan) == 1
    a = plan[0]
    assert a.symbol == "BTC/USDT" and a.side == "buy"
    assert abs(a.qty - 10.0) < 0.5    # 1000 USDT / 100 = ~10 BTC


def test_plan_vende_lo_que_sale_de_tendencia_primero():
    # Tengo BTC pero ahora el target es ETH → vender BTC (primero) y comprar ETH
    holdings = {"BTC/USDT": 10.0, "ETH/USDT": 0.0}
    prices = {"BTC/USDT": 100.0, "ETH/USDT": 50.0}
    weights = {"BTC/USDT": 0.0, "ETH/USDT": 1.0}
    plan = rebalance_plan(holdings, prices, weights, cash=0.0, filters=_filters(CFG.symbols), config=CFG)
    assert plan[0].side == "sell" and plan[0].symbol == "BTC/USDT"   # ventas primero
    assert any(a.side == "buy" and a.symbol == "ETH/USDT" for a in plan)


def test_plan_saltea_rebalanceos_de_polvo():
    # Holdings ya casi en el target → delta por debajo del min_notional → sin órdenes
    holdings = {"BTC/USDT": 10.0, "ETH/USDT": 0.0}
    prices = {"BTC/USDT": 100.0, "ETH/USDT": 50.0}
    weights = {"BTC/USDT": 1.0, "ETH/USDT": 0.0}
    plan = rebalance_plan(holdings, prices, weights, cash=1.0, filters=_filters(CFG.symbols), config=CFG)
    assert plan == []   # ya está balanceado (delta < min_notional)


# ── Orquestación ───────────────────────────────────────────────────

PFILT = {"step_size": 0.00001, "min_notional": 10.0, "min_price": 1.0,
         "max_price": 1e9, "ref_price": 100.0}


class FakePortfolioExchange:
    """Exchange multi-símbolo falso. `trends` define qué activos están en alza."""
    def __init__(self, trends, base=None, quote=10000.0):
        self.trends = trends                  # {symbol: True/False}
        self._base = base or {s: 0.0 for s in trends}
        self._quote = quote
        self.created = []

    def fetch_ohlcv(self, symbol, timeframe, limit):
        # Serie creciente (long) o decreciente (cash) según trends
        if self.trends[symbol]:
            return [[i, 0, 0, 0, 100 + i, 0] for i in range(60)]
        return [[i, 0, 0, 0, 200 - i, 0] for i in range(60)]

    def fetch_base_balance(self, symbol):
        return self._base.get(symbol, 0.0)

    def fetch_quote_balance(self, symbol):
        return self._quote

    def fetch_price(self, symbol):
        return 100.0

    def market_filters(self, symbol):
        return PFILT

    def fetch_order(self, coid, symbol):
        raise ValueError("no existe")

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        self.created.append((symbol, side, amount))
        return {"status": "closed", "filled": amount, "amount": amount,
                "average": price, "clientOrderId": params.get("clientOrderId") if params else ""}


def _deps(ex, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    j = Journal(db_path=str(tmp_path / "j.db"), text_path=str(tmp_path / "j.log"))
    return PortfolioDeps(ex, j, Notifier(token="", chat_id=""))


CFG4 = PortfolioConfig(symbols=("BTC/USDT", "ETH/USDT"), capital_fraction=0.95)


def test_run_portfolio_compra_los_en_tendencia(tmp_path, monkeypatch):
    ex = FakePortfolioExchange({"BTC/USDT": True, "ETH/USDT": True}, quote=10000.0)
    deps = _deps(ex, tmp_path, monkeypatch)
    r = run_portfolio_once(deps, CFG4, now_ts=0)
    assert r["action"] == "rebalanced"
    sides = {(s, side) for s, side, _ in ex.created}
    assert ("BTC/USDT", "buy") in sides and ("ETH/USDT", "buy") in sides


def test_run_portfolio_todo_cash_si_nada_en_tendencia(tmp_path, monkeypatch):
    # Ninguno en alza y sin holdings → nada que hacer (queda en cash)
    ex = FakePortfolioExchange({"BTC/USDT": False, "ETH/USDT": False})
    deps = _deps(ex, tmp_path, monkeypatch)
    r = run_portfolio_once(deps, CFG4, now_ts=0)
    assert r["action"] == "hold"
    assert ex.created == []


def test_run_portfolio_halt_no_opera(tmp_path, monkeypatch):
    ex = FakePortfolioExchange({"BTC/USDT": True, "ETH/USDT": True})
    deps = _deps(ex, tmp_path, monkeypatch)
    killswitch.engage_halt("test")
    r = run_portfolio_once(deps, CFG4, now_ts=0)
    assert r["action"] == "halted" and ex.created == []
