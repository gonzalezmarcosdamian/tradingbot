"""
test_bot.py — Tests de la iteración del loop (run_once).

Se prueba la orquestación entera con un exchange falso: que el kill-switch
frene todo, que una señal de entrada abra posición pasando por riesgo y órdenes,
que la señal de salida cierre, y que un resultado incierto fuerce halt.
"""

import killswitch
from bot import BotConfig, BotDeps, Action, run_once, run_forever
from journal import Journal
from notifier import Notifier
from risk import RiskConfig, RiskState
from state import StateStore, BotState
from strategy import sma_signal


CONFIG = BotConfig(symbol="BTC/USDT", timeframe="1h", fast=2, slow=3, lookback=20)
FILTERS = {"step_size": 0.0001, "min_notional": 10.0, "min_price": 1.0,
           "max_price": 1_000_000.0, "ref_price": 100.0}


def rising_rows(n=10):
    """Velas con cierre creciente → la rápida queda sobre la lenta (señal=1)."""
    return [[i, 0, 0, 0, 100 + i, 0] for i in range(n)]


def falling_rows(n=10):
    """Velas con cierre decreciente → la rápida queda bajo la lenta (señal=0)."""
    return [[i, 0, 0, 0, 200 - i, 0] for i in range(n)]


class FakeExchange:
    def __init__(self, rows, base=0.0, quote=10000.0, fill_outcome="closed"):
        self._rows = rows
        self._base = base
        self._quote = quote
        self._fill_outcome = fill_outcome
        self.created = []

    # data + balances
    def fetch_ohlcv(self, symbol, timeframe, limit):
        return self._rows

    def fetch_base_balance(self, symbol):
        return self._base

    def fetch_quote_balance(self, symbol):
        return self._quote

    def market_filters(self, symbol):
        return FILTERS

    # órdenes
    def fetch_order(self, client_order_id, symbol):
        raise ValueError("no existe")  # idempotencia: primer envío

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        self.created.append((side, amount))
        coid = params.get("clientOrderId") if params else ""
        if self._fill_outcome == "uncertain":
            raise ConnectionError("timeout")  # send_order intentará verificar
        return {"status": "closed", "filled": amount, "amount": amount,
                "average": price, "clientOrderId": coid}


def make_deps(exchange, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    store = StateStore(db_path=str(tmp_path / "bot.db"))
    journal = Journal(db_path=str(tmp_path / "j.db"), text_path=str(tmp_path / "j.log"))
    notifier = Notifier(token="", chat_id="")  # deshabilitado en tests
    return BotDeps(exchange, sma_signal, store, journal, notifier), store


def run(deps):
    return run_once(deps, CONFIG, RiskState(), RiskConfig())


# ── Kill-switch ────────────────────────────────────────────────────

def test_halt_activo_no_opera(tmp_path, monkeypatch):
    ex = FakeExchange(rising_rows())
    deps, _ = make_deps(ex, tmp_path, monkeypatch)
    killswitch.engage_halt("detenido a mano")
    res = run(deps)
    assert res.action == Action.HALTED
    assert ex.created == []  # no se envió ninguna orden


# ── Entrada ────────────────────────────────────────────────────────

def test_senal_alza_estando_fuera_abre_posicion(tmp_path, monkeypatch):
    ex = FakeExchange(rising_rows(), base=0.0, quote=10000.0)
    deps, store = make_deps(ex, tmp_path, monkeypatch)
    res = run(deps)
    assert res.action == Action.ENTERED
    assert store.load_state().in_position is True
    assert len(ex.created) == 1 and ex.created[0][0] == "buy"


def test_entrada_incierta_fuerza_halt(tmp_path, monkeypatch):
    ex = FakeExchange(rising_rows(), base=0.0, quote=10000.0, fill_outcome="uncertain")
    deps, _ = make_deps(ex, tmp_path, monkeypatch)
    res = run(deps)
    assert res.action == Action.UNCERTAIN
    assert killswitch.is_halted() is True  # ante la duda, detener


# ── Salida ─────────────────────────────────────────────────────────

def test_senal_baja_estando_dentro_cierra(tmp_path, monkeypatch):
    # base coincide con lo que cree el bot → reconciliación OK, sigue in_position
    ex = FakeExchange(falling_rows(), base=0.1, quote=100.0)
    deps, store = make_deps(ex, tmp_path, monkeypatch)
    store.save_state(BotState(in_position=True, base_qty=0.1,
                              avg_entry_price=150.0, quote_invested=15.0))
    res = run(deps)
    assert res.action == Action.EXITED
    assert store.load_state().in_position is False
    assert ex.created[0][0] == "sell"


# ── Mantener ───────────────────────────────────────────────────────

def test_senal_alza_estando_dentro_mantiene(tmp_path, monkeypatch):
    ex = FakeExchange(rising_rows(), base=0.05, quote=100.0)
    deps, store = make_deps(ex, tmp_path, monkeypatch)
    store.save_state(BotState(in_position=True, base_qty=0.05,
                              avg_entry_price=100.0, quote_invested=5.0))
    res = run(deps)
    assert res.action == Action.HOLD
    assert ex.created == []


def test_posicion_polvo_se_trata_como_flat(tmp_path, monkeypatch):
    # Posición por debajo del step (0.00001 < step 0.0001) → no operable → flat.
    ex = FakeExchange(falling_rows(), base=0.00001, quote=100.0)
    deps, store = make_deps(ex, tmp_path, monkeypatch)
    store.save_state(BotState(in_position=True, base_qty=0.00001, avg_entry_price=150.0))
    res = run(deps)
    assert res.action == Action.HOLD          # polvo → flat → sin venta
    assert store.load_state().in_position is False
    assert ex.created == []


def test_senal_baja_estando_fuera_mantiene(tmp_path, monkeypatch):
    ex = FakeExchange(falling_rows(), base=0.0, quote=10000.0)
    deps, _ = make_deps(ex, tmp_path, monkeypatch)
    res = run(deps)
    assert res.action == Action.HOLD


# ── Data insuficiente ──────────────────────────────────────────────

def test_pocas_velas_no_opera(tmp_path, monkeypatch):
    ex = FakeExchange(rising_rows(n=3))  # menos que slow+1 tras descartar la abierta
    deps, _ = make_deps(ex, tmp_path, monkeypatch)
    res = run(deps)
    assert res.action == Action.NO_DATA


# ── Loop continuo (run_forever) ────────────────────────────────────

def test_run_forever_corre_n_iteraciones_sin_dormir_al_final(tmp_path, monkeypatch):
    ex = FakeExchange(rising_rows(), base=0.0, quote=10000.0)
    deps, _ = make_deps(ex, tmp_path, monkeypatch)
    sleeps = []
    n = run_forever(deps, CONFIG, RiskState(), RiskConfig(),
                    sleep_seconds=3600, iterations=3,
                    sleep_fn=lambda s: sleeps.append(s))
    assert n == 3
    assert sleeps == [3600, 3600]  # duerme entre iteraciones, no tras la última


class ExplodingExchange(FakeExchange):
    """fetch_ohlcv revienta: el loop debe sobrevivir y alertar, no morir."""
    def fetch_ohlcv(self, symbol, timeframe, limit):
        raise RuntimeError("exchange caído")


def test_run_forever_sobrevive_a_excepciones(tmp_path, monkeypatch):
    ex = ExplodingExchange(rising_rows())
    deps, _ = make_deps(ex, tmp_path, monkeypatch)
    # No debe propagar la excepción: completa las 2 iteraciones igual.
    n = run_forever(deps, CONFIG, RiskState(), RiskConfig(),
                    sleep_seconds=0, iterations=2, sleep_fn=lambda s: None)
    assert n == 2
