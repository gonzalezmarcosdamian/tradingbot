"""
test_risk.py — Tests de la lógica de gestión de riesgo.

Para un módulo que decide cuánto y cuándo operar con plata real, los tests
son tan importantes como el módulo. Cubrimos cada restricción y casos límite.
"""

from datetime import date, timedelta
import pytest

from risk import (
    RiskConfig,
    RiskState,
    OrderProposal,
    Decision,
    approve_order,
)


# ── Fixtures de conveniencia ──────────────────────────────────────

def fresh_state(equity=1000.0, in_position=False, position_value=0.0):
    return RiskState(
        day=date.today(),
        day_start_equity=equity,
        realized_pnl_today=0.0,
        in_position=in_position,
        position_value=position_value,
    )


def buy_proposal(cash=1000.0, equity=1000.0, price=50000.0):
    return OrderProposal("buy", cash, equity, price)


def sell_proposal(equity=1000.0, price=50000.0):
    return OrderProposal("sell", 0.0, equity, price)


# ── Config: validaciones de cordura ───────────────────────────────

def test_config_rechaza_valores_invalidos():
    with pytest.raises(AssertionError):
        RiskConfig(capital_fraction=1.5)
    with pytest.raises(AssertionError):
        RiskConfig(stop_loss_pct=0)
    with pytest.raises(AssertionError):
        RiskConfig(max_exposure=2.0)


# ── Entradas (buy) ────────────────────────────────────────────────

def test_entrada_normal_aprobada():
    res = approve_order(buy_proposal(), fresh_state(), RiskConfig())
    assert res.decision == Decision.APPROVED
    # 95% de 1000
    assert res.size_quote == pytest.approx(950.0)
    # SL 2% bajo 50000
    assert res.stop_price == pytest.approx(49000.0)
    # TP off por defecto
    assert res.take_profit_price is None


def test_take_profit_cuando_esta_activado():
    cfg = RiskConfig(use_take_profit=True)
    res = approve_order(buy_proposal(), fresh_state(), cfg)
    assert res.take_profit_price == pytest.approx(52000.0)  # 4% sobre 50000


def test_entrada_rechazada_si_ya_en_posicion():
    state = fresh_state(in_position=True, position_value=900.0)
    res = approve_order(buy_proposal(), state, RiskConfig())
    assert res.decision == Decision.REJECTED
    assert "posición abierta" in res.reason


def test_entrada_rechazada_sin_capital():
    res = approve_order(buy_proposal(cash=0.0), fresh_state(), RiskConfig())
    assert res.decision == Decision.REJECTED
    assert "capital" in res.reason.lower()


def test_circuit_breaker_corta_entradas():
    # Equity inicial 1000, perdimos 60 (6%) > límite 5%
    state = fresh_state(equity=1000.0)
    state.realized_pnl_today = -60.0
    res = approve_order(buy_proposal(), state, RiskConfig())
    assert res.decision == Decision.REJECTED
    assert "Circuit breaker" in res.reason


def test_circuit_breaker_no_corta_si_perdida_menor():
    state = fresh_state(equity=1000.0)
    state.realized_pnl_today = -40.0  # 4% < 5%
    res = approve_order(buy_proposal(), state, RiskConfig())
    assert res.decision == Decision.APPROVED


def test_exposicion_maxima_limita_size():
    # Ya tenemos 900 comprometidos, equity 1000, max_exposure 1.0 → room 100
    state = fresh_state(equity=1000.0, in_position=False, position_value=900.0)
    res = approve_order(buy_proposal(cash=1000.0, equity=1000.0), state, RiskConfig())
    assert res.decision == Decision.APPROVED
    assert res.size_quote == pytest.approx(100.0)  # recortado al room


def test_exposicion_maxima_rechaza_si_lleno():
    state = fresh_state(equity=1000.0, position_value=1000.0)
    res = approve_order(buy_proposal(), state, RiskConfig())
    assert res.decision == Decision.REJECTED
    assert "Exposición máxima" in res.reason


# ── Salidas (sell) ────────────────────────────────────────────────

def test_salida_aprobada_si_en_posicion():
    state = fresh_state(in_position=True, position_value=950.0)
    res = approve_order(sell_proposal(), state, RiskConfig())
    assert res.decision == Decision.APPROVED
    assert res.size_quote == pytest.approx(950.0)


def test_salida_rechazada_sin_posicion():
    res = approve_order(sell_proposal(), fresh_state(in_position=False), RiskConfig())
    assert res.decision == Decision.REJECTED
    assert "No hay posición" in res.reason


def test_salida_permitida_aun_con_circuit_breaker():
    # Salir siempre debe poder, incluso con breaker activo
    state = fresh_state(equity=1000.0, in_position=True, position_value=950.0)
    state.realized_pnl_today = -200.0  # breaker activo
    res = approve_order(sell_proposal(), state, RiskConfig())
    assert res.decision == Decision.APPROVED


# ── Roll diario ───────────────────────────────────────────────────

def test_roll_diario_resetea_contadores():
    ayer = date.today() - timedelta(days=1)
    state = RiskState(day=ayer, day_start_equity=500.0, realized_pnl_today=-100.0)
    # Al evaluar hoy, debe resetear el PnL del día y tomar el nuevo equity
    approve_order(buy_proposal(equity=1000.0), state, RiskConfig(), today=date.today())
    assert state.day == date.today()
    assert state.realized_pnl_today == 0.0
    assert state.day_start_equity == 1000.0
