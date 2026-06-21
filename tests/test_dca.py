"""
test_dca.py — Tests del Smart DCA con presupuesto por período.

Cubre: el análisis (múltiplo por desvío de media), el reparto de la cuota justa
sin pasarse del presupuesto (escenario 50/20/10/20 del ejemplo), los topes, y
la orquestación de una compra contra un exchange falso.
"""

import killswitch
from dca import (
    DCAConfig, DCAState, DCAStore, DCADeps, DCADecision,
    simple_ma, rsi_last, analyze, maybe_reset_period, decide,
    run_dca_once, compare,
)
from journal import Journal
from notifier import Notifier


# ── Indicadores ────────────────────────────────────────────────────

def test_simple_ma():
    assert simple_ma([1, 2, 3, 4], 2) == 3.5
    assert simple_ma([1, 2], 5) is None  # data insuficiente


def test_rsi_subida_pura_da_100():
    assert rsi_last(list(range(1, 30)), 14) == 100.0


# ── Análisis / múltiplo ────────────────────────────────────────────

# Config que aísla el efecto de la media (RSI desactivado por falta de data).
MA_ONLY = DCAConfig(ma_period=30, rsi_period=999, sensitivity=5.0,
                    min_mult=0.3, max_mult=2.5)


def test_multiplo_mayor_cuando_esta_barato():
    closes = [100.0] * 30
    a = analyze(closes, price=90.0, config=MA_ONLY)  # 10% bajo la media
    assert a.multiplier == 1.5  # 1 - 5*(-0.1)


def test_multiplo_menor_cuando_esta_caro():
    closes = [100.0] * 30
    a = analyze(closes, price=110.0, config=MA_ONLY)
    assert a.multiplier == 0.5


def test_multiplo_se_acota_al_maximo():
    closes = [100.0] * 30
    a = analyze(closes, price=50.0, config=MA_ONLY)  # -50% → 3.5, capado a 2.5
    assert a.multiplier == 2.5


def test_smart_off_multiplo_uno():
    closes = [100.0] * 30
    cfg = DCAConfig(smart=False)
    assert analyze(closes, 50.0, cfg).multiplier == 1.0


# ── Reset de período ───────────────────────────────────────────────

def test_reset_primera_vez():
    cfg = DCAConfig(period_seconds=1000)
    s = maybe_reset_period(DCAState(), cfg, now_ts=500)
    assert s.period_start_ts == 500 and s.spent_this_period == 0.0


def test_no_resetea_dentro_del_periodo():
    cfg = DCAConfig(period_seconds=1000)
    s = DCAState(period_start_ts=100, spent_this_period=30, buys_this_period=1)
    out = maybe_reset_period(s, cfg, now_ts=600)
    assert out.spent_this_period == 30 and out.buys_this_period == 1


def test_resetea_al_vencer_periodo():
    cfg = DCAConfig(period_seconds=1000)
    s = DCAState(period_start_ts=100, spent_this_period=80, buys_this_period=4)
    out = maybe_reset_period(s, cfg, now_ts=1200)
    assert out.period_start_ts == 1200 and out.spent_this_period == 0.0


# ── Reparto del presupuesto (escenario 50/20/10/20) ────────────────

def _apply(state, decision, ts):
    """Aplica una compra al estado (como hace run_dca_once)."""
    state.spent_this_period += decision.quote_amount
    state.buys_this_period += 1
    state.last_buy_ts = ts
    return state


def test_reparto_no_excede_presupuesto_y_lo_usa_todo():
    # 100 de presupuesto, 4 compras, intervalo. Multiplos segun "momento".
    cfg = DCAConfig(period_budget=100, buys_per_period=4, period_seconds=4000,
                    min_quote=1, min_mult=0.1, max_mult=5.0)
    iv = cfg.interval_seconds  # 1000
    state = DCAState()
    cash = 10_000
    amounts = []

    # Semana 1: caída fuerte → x2 → cuota 25 * 2 = 50
    d = decide(cfg, state, now_ts=0, available_cash=cash, multiplier=2.0)
    amounts.append(d.quote_amount); _apply(state, d, 0)
    # Semana 2: leve dip → x1.2 → (50/3)=16.67 * 1.2 = 20
    d = decide(cfg, state, now_ts=iv, available_cash=cash, multiplier=1.2)
    amounts.append(d.quote_amount); _apply(state, d, iv)
    # Semana 3: caro → x0.667 → (30/2)=15 * 0.667 ≈ 10
    d = decide(cfg, state, now_ts=2 * iv, available_cash=cash, multiplier=0.667)
    amounts.append(d.quote_amount); _apply(state, d, 2 * iv)
    # Semana 4: última → deploya lo que queda (capado al presupuesto), ~20
    d = decide(cfg, state, now_ts=3 * iv, available_cash=cash, multiplier=1.5)
    amounts.append(d.quote_amount); _apply(state, d, 3 * iv)

    assert round(amounts[0]) == 50
    assert round(amounts[1]) == 20
    assert round(amounts[2]) == 10
    assert round(amounts[3]) == 20
    assert round(sum(amounts), 2) == 100.0  # usó todo el presupuesto, sin pasarse


def test_quinta_compra_del_periodo_se_rechaza():
    cfg = DCAConfig(period_budget=100, buys_per_period=4, period_seconds=4000)
    state = DCAState(buys_this_period=4, spent_this_period=100,
                     last_buy_ts=0, period_start_ts=0)
    d = decide(cfg, state, now_ts=3500, available_cash=1000, multiplier=1.0)
    assert d.should_buy is False


def test_respeta_intervalo_entre_compras():
    cfg = DCAConfig(period_budget=100, buys_per_period=4, period_seconds=4000)
    state = DCAState(last_buy_ts=1000, buys_this_period=1, period_start_ts=0)
    d = decide(cfg, state, now_ts=1500, available_cash=1000, multiplier=1.0)  # < 1000 de intervalo
    assert d.should_buy is False


def test_cash_insuficiente_rechaza():
    cfg = DCAConfig(period_budget=100, buys_per_period=4, min_quote=5)
    d = decide(cfg, DCAState(), now_ts=0, available_cash=2.0, multiplier=1.0)
    assert d.should_buy is False


# ── Orquestación contra exchange falso ─────────────────────────────

FILTERS = {"step_size": 0.00001, "min_notional": 5.0, "min_price": 1.0,
           "max_price": 1e9, "ref_price": 100.0}


class FakeDCAExchange:
    def __init__(self, price=100.0, closes=None, quote=10_000.0, fill=True):
        self.price = price
        self._closes = closes or [100.0] * 40
        self._quote = quote
        self.fill = fill
        self.created = []

    def fetch_price(self, s): return self.price
    def fetch_ohlcv(self, s, tf, limit):
        return [[i, 0, 0, 0, c, 0] for i, c in enumerate(self._closes)]
    def fetch_quote_balance(self, s): return self._quote
    def fetch_base_balance(self, s): return 0.0
    def market_filters(self, s): return FILTERS
    def fetch_order(self, coid, s): raise ValueError("no existe")
    def create_order(self, symbol, type, side, amount, price=None, params=None):
        self.created.append((side, amount))
        if not self.fill:
            raise ConnectionError("timeout")
        coid = params.get("clientOrderId") if params else ""
        return {"status": "closed", "filled": amount, "amount": amount,
                "average": price, "clientOrderId": coid}


def make_deps(ex, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    journal = Journal(db_path=str(tmp_path / "j.db"), text_path=str(tmp_path / "j.log"))
    return DCADeps(ex, journal, Notifier(token="", chat_id="")), DCAStore(str(tmp_path / "dca.json"))


def test_run_dca_compra_y_persiste(tmp_path, monkeypatch):
    cfg = DCAConfig(period_budget=100, buys_per_period=4, smart=False)
    ex = FakeDCAExchange(price=100.0)
    deps, store = make_deps(ex, tmp_path, monkeypatch)
    res = run_dca_once(deps, cfg, store, now_ts=0)
    assert res.bought is True
    assert round(res.quote_amount) == 25  # cuota pareja con smart off
    st = store.load()
    assert st.buys_this_period == 1 and round(st.spent_this_period) == 25
    assert ex.created[0][0] == "buy"


def test_run_dca_halt_no_compra(tmp_path, monkeypatch):
    cfg = DCAConfig(smart=False)
    ex = FakeDCAExchange()
    deps, store = make_deps(ex, tmp_path, monkeypatch)
    killswitch.engage_halt("test")
    res = run_dca_once(deps, cfg, store, now_ts=0)
    assert res.bought is False and ex.created == []


def test_run_dca_compra_incierta_hace_halt(tmp_path, monkeypatch):
    cfg = DCAConfig(period_budget=100, buys_per_period=4, smart=False)
    ex = FakeDCAExchange(price=100.0, fill=False)  # create_order tira timeout
    deps, store = make_deps(ex, tmp_path, monkeypatch)
    res = run_dca_once(deps, cfg, store, now_ts=0)
    assert res.bought is False
    assert killswitch.is_halted() is True  # incierta → halt


# ── Evaluación vs DCA plano ────────────────────────────────────────

def test_compare_smart_mas_barato_da_edge_positivo():
    # Mismo gasto, pero smart acumuló más BTC → costo promedio menor → edge > 0
    st = DCAState(total_spent=100, smart_total_btc=0.0011,
                  flat_total_spent=100, flat_total_btc=0.0010)
    c = compare(st)
    assert c["smart_avg_cost"] < c["flat_avg_cost"]
    assert c["smart_edge_pct"] > 0


def test_run_dca_guarda_contrafactico_plano(tmp_path, monkeypatch):
    cfg = DCAConfig(period_budget=100, buys_per_period=4, smart=False)
    ex = FakeDCAExchange(price=100.0)
    deps, store = make_deps(ex, tmp_path, monkeypatch)
    run_dca_once(deps, cfg, store, now_ts=0)
    st = store.load()
    assert st.smart_total_btc > 0 and st.flat_total_btc > 0
    assert round(st.flat_total_spent) == 25            # cuota plana = 100/4
    # con smart off, la compra smart ≈ plana (difieren solo por el redondeo al
    # step real del exchange; el plano es teórico quote/precio)
    assert abs(st.smart_total_btc - st.flat_total_btc) < 1e-3
    assert (tmp_path / "dca_eval.csv").exists()         # CSV de evaluación escrito
