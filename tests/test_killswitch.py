"""
test_killswitch.py — Tests del halt flag y del panic-close.

Foco en los escenarios peligrosos: que el halt sobreviva, que el panic detenga
SIEMPRE aunque la venta falle, y que reporte honestamente si no pudo cerrar.
"""

import killswitch
from killswitch import panic_close, PanicReport


# ── HALT FLAG ──────────────────────────────────────────────────────

def test_halt_engage_y_consulta(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert killswitch.is_halted() is False
    killswitch.engage_halt("prueba")
    assert killswitch.is_halted() is True
    assert killswitch.halt_reason() == "prueba"


def test_halt_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    killswitch.engage_halt("x")
    assert killswitch.clear_halt() is True
    assert killswitch.is_halted() is False
    assert killswitch.clear_halt() is False  # ya no había nada que limpiar


def test_halt_reason_none_sin_halt(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert killswitch.halt_reason() is None


# ── PANIC-CLOSE ────────────────────────────────────────────────────

DEFAULT_FILTERS = {"step_size": 0.0001, "min_notional": 10.0, "ref_price": 50000.0}


class FakePanicExchange:
    def __init__(self, base=0.0, filters=None,
                 fail_cancel=False, fail_balance=False, fail_sell=False):
        self._base = base
        self._filters = filters or DEFAULT_FILTERS
        self._fail_cancel = fail_cancel
        self._fail_balance = fail_balance
        self._fail_sell = fail_sell
        self.sell_calls = 0
        self.cancel_calls = 0

    def cancel_all_orders(self, symbol):
        self.cancel_calls += 1
        if self._fail_cancel:
            raise ConnectionError("timeout cancel")
        return [{"id": "1"}, {"id": "2"}]

    def fetch_base_balance(self, symbol):
        if self._fail_balance:
            raise ConnectionError("timeout balance")
        return self._base

    def create_market_sell(self, symbol, amount):
        self.sell_calls += 1
        if self._fail_sell:
            raise ConnectionError("timeout sell")
        return {"status": "closed", "filled": amount}

    def market_filters(self, symbol):
        return self._filters


def test_panic_cierra_posicion_y_detiene(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    ex = FakePanicExchange(base=0.5)
    rep = panic_close(ex, "BTC/USDT")
    assert isinstance(rep, PanicReport)
    assert rep.halted is True
    assert rep.success is True
    assert rep.sold_amount == 0.5
    assert rep.orders_canceled == 2
    assert killswitch.is_halted() is True  # quedó detenido


def test_panic_sin_posicion_no_vende(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    ex = FakePanicExchange(base=0.0)
    rep = panic_close(ex, "BTC/USDT")
    assert rep.success is True
    assert rep.sold_amount == 0.0
    assert ex.sell_calls == 0  # no había nada que vender


def test_panic_detiene_aunque_falle_la_venta(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    ex = FakePanicExchange(base=0.5, fail_sell=True)
    rep = panic_close(ex, "BTC/USDT", attempts=2)
    # Lo crítico: aunque la venta no entre, el bot QUEDA detenido.
    assert rep.halted is True
    assert killswitch.is_halted() is True
    assert rep.success is False          # honesto: no se pudo cerrar
    assert ex.sell_calls == 2            # reintentó


def test_panic_sin_balance_no_garantiza_cierre_pero_detiene(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    ex = FakePanicExchange(fail_balance=True)
    rep = panic_close(ex, "BTC/USDT", attempts=2)
    assert rep.halted is True
    assert rep.success is False  # sin saber el balance, no podemos afirmar cierre


def test_panic_polvo_menor_al_step_se_considera_plano(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    ex = FakePanicExchange(base=0.00005)  # menor al step 0.0001
    rep = panic_close(ex, "BTC/USDT")
    assert rep.success is True
    assert ex.sell_calls == 0
