"""
test_state.py — Tests de persistencia y reconciliación.

La reconciliación es crítica en cuenta compartida: un error acá puede hacer
que el bot opere sobre estado incierto. Cubrimos round-trip de persistencia
y cada rama de la reconciliación con un exchange falso.
"""

import os
import tempfile
import pytest

from state import (
    BotState,
    StateStore,
    reconcile,
    ReconcileReport,
)


# ── Exchange falso para testear reconcile sin tocar Binance ───────

class FakeExchange:
    def __init__(self, orders: dict, base_balance: float = 0.0):
        # orders: { client_order_id: {status, filled, average, side} }
        self._orders = orders
        self._base_balance = base_balance

    def fetch_order(self, client_order_id, symbol):
        if client_order_id not in self._orders:
            raise ValueError(f"orden {client_order_id} no encontrada")
        return self._orders[client_order_id]

    def fetch_base_balance(self, symbol):
        return self._base_balance


class BrokenExchange:
    """Simula caída de conexión: siempre falla."""
    def fetch_order(self, client_order_id, symbol):
        raise ConnectionError("sin conexión al exchange")

    def fetch_base_balance(self, symbol):
        raise ConnectionError("sin conexión al exchange")


# ── Persistencia: round-trip ──────────────────────────────────────

def test_persistencia_round_trip():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "test.db")
        store = StateStore(db)

        st = BotState(in_position=True, base_qty=0.02, avg_entry_price=50000.0,
                      quote_invested=1000.0, known_orders=["bot-001"])
        store.save_state(st)

        store2 = StateStore(db)  # reabrir desde disco
        loaded = store2.load_state()
        assert loaded.in_position is True
        assert loaded.base_qty == pytest.approx(0.02)
        assert loaded.known_orders == ["bot-001"]
        store.close(); store2.close()


def test_estado_limpio_primera_vez():
    with tempfile.TemporaryDirectory() as d:
        store = StateStore(os.path.join(d, "fresh.db"))
        st = store.load_state()
        assert st.in_position is False
        assert st.base_qty == 0.0
        store.close()


def test_record_order_persiste():
    with tempfile.TemporaryDirectory() as d:
        store = StateStore(os.path.join(d, "ord.db"))
        store.record_order("bot-001", "buy", 0.02, 50000.0, "closed")
        row = store.conn.execute(
            "SELECT side, status FROM known_orders WHERE client_order_id='bot-001'"
        ).fetchone()
        assert row == ("buy", "closed")
        store.close()


# ── Reconciliación ────────────────────────────────────────────────

def test_reconcile_todo_cerrado_es_seguro():
    state = BotState(in_position=True, base_qty=0.02, known_orders=["bot-001"])
    ex = FakeExchange(
        {"bot-001": {"status": "closed", "filled": 0.02,
                     "average": 50000.0, "side": "buy"}},
        base_balance=0.02,  # coincide con la contabilidad interna
    )
    rep = reconcile(state, ex)
    assert rep.safe_to_trade is True
    assert all(d["severity"] != "halt" for d in rep.discrepancies)


def test_reconcile_orden_abierta_hace_halt():
    state = BotState(known_orders=["bot-002"])
    ex = FakeExchange(
        {"bot-002": {"status": "open", "filled": 0.0,
                     "average": None, "side": "buy"}},
        base_balance=0.0,
    )
    rep = reconcile(state, ex)
    assert rep.safe_to_trade is False
    assert any(d["severity"] == "halt" for d in rep.discrepancies)


def test_reconcile_cancelada_sin_fill_es_info():
    state = BotState(known_orders=["bot-003"])
    ex = FakeExchange(
        {"bot-003": {"status": "canceled", "filled": 0.0,
                     "average": None, "side": "buy"}},
        base_balance=0.0,
    )
    rep = reconcile(state, ex)
    assert rep.safe_to_trade is True
    assert any(d["severity"] == "info" for d in rep.discrepancies)


def test_reconcile_sin_conexion_hace_halt():
    # Si no podemos verificar, NO operamos (conservador)
    state = BotState(known_orders=["bot-004"])
    rep = reconcile(state, BrokenExchange())
    assert rep.safe_to_trade is False
    assert any(d["severity"] == "halt" for d in rep.discrepancies)


def test_reconcile_sin_ordenes_es_seguro():
    state = BotState(known_orders=[])
    rep = reconcile(state, FakeExchange({}, base_balance=0.0))
    assert rep.safe_to_trade is True
    assert rep.discrepancies == []


# ── Verificación contra balance real (cuenta dedicada) ────────────

def test_balance_coincide_dentro_de_tolerancia():
    state = BotState(in_position=True, base_qty=0.02, known_orders=[])
    # 0.0199 vs 0.02 = 0.5% de diff, dentro de tolerancia
    ex = FakeExchange({}, base_balance=0.0199)
    rep = reconcile(state, ex)
    assert rep.safe_to_trade is True
    # El estado se alinea al valor real del exchange
    assert rep.state.base_qty == pytest.approx(0.0199)


def test_balance_adopta_posicion_si_bot_creia_estar_fuera():
    state = BotState(in_position=False, base_qty=0.0, known_orders=[])
    ex = FakeExchange({}, base_balance=0.02)  # hay BTC real
    rep = reconcile(state, ex)
    assert rep.safe_to_trade is True  # adoptar es seguro
    assert rep.state.in_position is True
    assert rep.state.base_qty == pytest.approx(0.02)
    assert any(d["severity"] == "adopt" for d in rep.discrepancies)


def test_balance_marca_fuera_si_no_hay_btc():
    state = BotState(in_position=True, base_qty=0.02, quote_invested=1000.0,
                     known_orders=[])
    ex = FakeExchange({}, base_balance=0.0)  # se vendió mientras caído
    rep = reconcile(state, ex)
    assert rep.safe_to_trade is True
    assert rep.state.in_position is False
    assert rep.state.base_qty == 0.0
    assert any(d["severity"] == "adopt" for d in rep.discrepancies)


def test_balance_discrepancia_grande_hace_halt():
    state = BotState(in_position=True, base_qty=0.02, known_orders=[])
    ex = FakeExchange({}, base_balance=0.015)  # 25% de diff, inexplicable
    rep = reconcile(state, ex)
    assert rep.safe_to_trade is False
    assert any(d["severity"] == "halt" and d.get("check") == "balance"
               for d in rep.discrepancies)


def test_balance_ambos_en_cero_es_seguro():
    state = BotState(in_position=False, base_qty=0.0, known_orders=[])
    ex = FakeExchange({}, base_balance=0.0)
    rep = reconcile(state, ex)
    assert rep.safe_to_trade is True
