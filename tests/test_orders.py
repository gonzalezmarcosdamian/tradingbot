"""
test_orders.py — Tests de validación y envío idempotente.

Foco en los escenarios peligrosos: doble envío por timeout, órdenes mal
formadas, fills parciales (limit) y estado incierto.
"""

import pytest

from orders import (
    OrderRequest,
    OrderOutcome,
    make_client_order_id,
    validate_order,
    send_order,
    _round_to_step,
)


DEFAULT_FILTERS = {
    "min_notional": 10.0,
    "step_size": 0.0001,
    "min_price": 1.0,
    "max_price": 1_000_000.0,
    "ref_price": 50000.0,
}


class FakeExchange:
    """Exchange configurable para simular cada escenario."""
    def __init__(self, base=1.0, quote=100000.0, filters=None,
                 existing=None, create_response=None, raise_on_create=False,
                 raise_on_fetch=False):
        self._base = base
        self._quote = quote
        self._filters = filters or DEFAULT_FILTERS
        self._existing = existing      # respuesta de fetch_order si "ya existe"
        self._create_response = create_response
        self._raise_on_create = raise_on_create
        self._raise_on_fetch = raise_on_fetch
        self.create_calls = 0

    def market_filters(self, symbol):
        return self._filters

    def fetch_base_balance(self, symbol):
        return self._base

    def fetch_quote_balance(self, symbol):
        return self._quote

    def fetch_order(self, client_order_id, symbol):
        if self._raise_on_fetch:
            raise ConnectionError("timeout en fetch")
        if self._existing is None:
            raise ValueError("no existe")
        return self._existing

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        self.create_calls += 1
        if self._raise_on_create:
            raise ConnectionError("timeout en create")
        resp = dict(self._create_response or {})
        resp.setdefault("clientOrderId", params.get("clientOrderId") if params else "")
        return resp


def buy_market(amount=0.01):
    return OrderRequest("BTC/USDT", "buy", "market", amount,
                        price=50000.0, intent_id="candle-123")


# ── Idempotencia ──────────────────────────────────────────────────

def test_client_order_id_es_deterministico():
    req = buy_market()
    assert make_client_order_id(req) == make_client_order_id(req)


def test_client_order_id_cambia_con_la_intencion():
    a = make_client_order_id(buy_market(0.01))
    b = make_client_order_id(buy_market(0.02))
    assert a != b


def test_no_reenvia_si_la_orden_ya_existe():
    # Simula reintento del mismo intent: la orden ya está ejecutada
    existing = {"status": "closed", "filled": 0.01, "amount": 0.01,
                "average": 50000.0, "clientOrderId": "bot-x"}
    ex = FakeExchange(existing=existing)
    res = send_order(buy_market(), ex)
    assert res.outcome == OrderOutcome.FILLED
    assert ex.create_calls == 0  # NO se reenvió


# ── Validación ────────────────────────────────────────────────────

def test_rechaza_limit_sin_precio():
    req = OrderRequest("BTC/USDT", "buy", "limit", 0.01, price=None)
    ex = FakeExchange()
    assert validate_order(req, ex) is not None


def test_rechaza_amount_negativo():
    req = OrderRequest("BTC/USDT", "buy", "market", -1.0, price=50000.0)
    assert validate_order(req, FakeExchange()) is not None


def test_rechaza_bajo_notional_minimo():
    # 0.0001 BTC * 50000 = 5 USDT < min_notional 10
    req = OrderRequest("BTC/USDT", "buy", "market", 0.0001, price=50000.0)
    assert validate_order(req, FakeExchange()) is not None


def test_rechaza_saldo_insuficiente_compra():
    req = buy_market(0.01)  # 0.01*50000 = 500 USDT
    ex = FakeExchange(quote=100.0)  # solo 100 USDT
    assert validate_order(req, ex) is not None


def test_rechaza_base_insuficiente_venta():
    req = OrderRequest("BTC/USDT", "sell", "market", 0.5, price=50000.0)
    ex = FakeExchange(base=0.01)  # solo 0.01 BTC
    assert validate_order(req, ex) is not None


def test_orden_valida_pasa():
    assert validate_order(buy_market(0.01), FakeExchange()) is None


def test_round_to_step():
    assert _round_to_step(0.012345, 0.0001) == pytest.approx(0.0123)
    assert _round_to_step(0.00005, 0.0001) == 0.0  # menor que el step


# ── Envío y clasificación de resultados ───────────────────────────

def test_market_ejecutada_devuelve_filled():
    resp = {"status": "closed", "filled": 0.01, "amount": 0.01, "average": 50010.0}
    ex = FakeExchange(create_response=resp)
    res = send_order(buy_market(0.01), ex)
    assert res.outcome == OrderOutcome.FILLED
    assert res.filled == pytest.approx(0.01)


def test_limit_parcial_devuelve_partial():
    resp = {"status": "open", "filled": 0.004, "amount": 0.01, "average": 49000.0}
    ex = FakeExchange(create_response=resp)
    req = OrderRequest("BTC/USDT", "buy", "limit", 0.01, price=49000.0)
    res = send_order(req, ex)
    assert res.outcome == OrderOutcome.PARTIAL


def test_limit_abierta_devuelve_open():
    resp = {"status": "open", "filled": 0.0, "amount": 0.01}
    ex = FakeExchange(create_response=resp)
    req = OrderRequest("BTC/USDT", "buy", "limit", 0.01, price=40000.0)
    res = send_order(req, ex)
    assert res.outcome == OrderOutcome.OPEN


class FetchAfterCreateExchange(FakeExchange):
    """fetch_order falla la 1ra vez (idempotencia: no existe) y, tras un
    create que tira timeout, devuelve la orden en la verificación posterior."""
    def __init__(self, recovered_order, **kw):
        super().__init__(raise_on_create=True, **kw)
        self._recovered = recovered_order
        self._fetch_count = 0

    def fetch_order(self, client_order_id, symbol):
        self._fetch_count += 1
        if self._fetch_count == 1:
            raise ValueError("no existe todavía")  # chequeo de idempotencia
        return self._recovered  # verificación post-timeout: sí entró


def test_timeout_pero_orden_entro_se_recupera():
    # create_order tira timeout; la verificación posterior por ID la encuentra
    recovered = {"status": "closed", "filled": 0.01, "amount": 0.01, "average": 50000.0}
    ex = FetchAfterCreateExchange(recovered)
    res = send_order(buy_market(0.01), ex)
    assert res.outcome == OrderOutcome.FILLED
    assert ex.create_calls == 1  # se intentó crear
    assert ex._fetch_count == 2  # idempotencia + verificación post-timeout


def test_timeout_y_no_se_puede_verificar_es_uncertain():
    # create falla Y fetch también falla → estado incierto
    ex = FakeExchange(existing=None, raise_on_create=True, raise_on_fetch=True)
    res = send_order(buy_market(0.01), ex)
    assert res.outcome == OrderOutcome.UNCERTAIN
    assert res.client_order_id  # devolvemos el ID para reconciliar


class InsufficientBalanceExchange(FakeExchange):
    """create_order falla con un rechazo DEFINITIVO (saldo insuficiente)."""
    def create_order(self, symbol, type, side, amount, price=None, params=None):
        self.create_calls += 1
        raise Exception("Account has insufficient balance for requested action.")


def test_rechazo_definitivo_es_rejected_no_uncertain():
    # Un "insufficient balance" NO es incertidumbre de red: es rechazo → no halt.
    ex = InsufficientBalanceExchange()
    res = send_order(buy_market(0.01), ex)
    assert res.outcome == OrderOutcome.REJECTED
    assert "insufficient" in res.reason.lower()
