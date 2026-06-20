"""
test_config_versions.py — Tests del versionado y la jaula de rangos duros.

La validación de rangos es la garantía de seguridad del aprendizaje, así que
es lo más testeado: ningún valor fuera de rango debe poder guardarse.
"""

import os
import tempfile
import pytest

from config_versions import (
    ConfigStore,
    validate_params,
    DEFAULT_PARAMS,
    ADJUSTABLE_RANGES,
    CORE_INVARIANTS,
)


def store(tmp):
    return ConfigStore(db_path=os.path.join(tmp, "config.db"))


def valid_params(**overrides):
    p = dict(DEFAULT_PARAMS)
    p.update(overrides)
    return p


# ── Validación: la jaula ──────────────────────────────────────────

def test_default_es_valido():
    assert validate_params(DEFAULT_PARAMS).valid is True


def test_rechaza_fast_ma_fuera_de_rango():
    assert validate_params(valid_params(fast_ma=5)).valid is False
    assert validate_params(valid_params(fast_ma=100)).valid is False


def test_rechaza_capital_fraction_excesivo():
    # 1.0 está fuera del rango (0.50, 0.95)
    res = validate_params(valid_params(capital_fraction=1.0))
    assert res.valid is False


def test_rechaza_daily_loss_limit_excesivo():
    assert validate_params(valid_params(daily_loss_limit=0.20)).valid is False


def test_rechaza_fast_mayor_o_igual_que_slow():
    res = validate_params(valid_params(fast_ma=50, slow_ma=50))
    assert res.valid is False
    assert any("debe ser <" in e for e in res.errors)


def test_rechaza_timeframe_no_permitido():
    assert validate_params(valid_params(timeframe="5m")).valid is False


def test_rechaza_parametro_faltante():
    incompleto = dict(DEFAULT_PARAMS)
    del incompleto["stop_loss_pct"]
    assert validate_params(incompleto).valid is False


def test_acepta_valores_en_los_bordes():
    # Los extremos exactos del rango deben ser válidos
    p = valid_params(fast_ma=10, slow_ma=200, capital_fraction=0.95,
                     stop_loss_pct=0.05, daily_loss_limit=0.08)
    assert validate_params(p).valid is True


# ── Versionado, activación, rollback ──────────────────────────────

def test_siembra_default_al_crear():
    with tempfile.TemporaryDirectory() as tmp:
        cs = store(tmp)
        active = cs.get_active()
        assert active.fast_ma == DEFAULT_PARAMS["fast_ma"]
        cs.close()


def test_propose_version_valida_y_guarda():
    with tempfile.TemporaryDirectory() as tmp:
        cs = store(tmp)
        v = cs.propose_version(valid_params(fast_ma=30), reason="prueba")
        assert v > 0
        cs.close()


def test_propose_version_rechaza_invalido_sin_guardar():
    with tempfile.TemporaryDirectory() as tmp:
        cs = store(tmp)
        before = len(cs.history(limit=999))
        with pytest.raises(ValueError):
            cs.propose_version(valid_params(capital_fraction=2.0), reason="malo")
        after = len(cs.history(limit=999))
        assert after == before  # no se guardó nada
        cs.close()


def test_activate_y_get_active():
    with tempfile.TemporaryDirectory() as tmp:
        cs = store(tmp)
        v = cs.propose_version(valid_params(fast_ma=40, slow_ma=150),
                               reason="nuevos params", activate=True)
        active = cs.get_active()
        assert active.fast_ma == 40
        assert cs.get_active_version_number() == v
        cs.close()


def test_rollback_vuelve_a_version_anterior():
    with tempfile.TemporaryDirectory() as tmp:
        cs = store(tmp)
        v1 = cs.get_active_version_number()  # default sembrada
        v2 = cs.propose_version(valid_params(fast_ma=35), reason="cambio",
                                activate=True)
        assert cs.get_active().fast_ma == 35
        # Rollback a la versión original
        cs.rollback(v1)
        assert cs.get_active().fast_ma == DEFAULT_PARAMS["fast_ma"]
        assert cs.get_active_version_number() == v1
        cs.close()


def test_activate_version_inexistente_falla():
    with tempfile.TemporaryDirectory() as tmp:
        cs = store(tmp)
        with pytest.raises(ValueError):
            cs.activate(9999)
        cs.close()


def test_historial_es_append_only():
    with tempfile.TemporaryDirectory() as tmp:
        cs = store(tmp)
        cs.propose_version(valid_params(fast_ma=30), reason="v a")
        cs.propose_version(valid_params(fast_ma=40), reason="v b")
        hist = cs.history()
        # default + 2 = 3 versiones, ninguna borrada
        assert len(hist) == 3
        cs.close()


# ── Núcleo no-ajustable ───────────────────────────────────────────

def test_nucleo_blindado_no_esta_en_los_ajustables():
    # Ninguna clave del núcleo debe aparecer como ajustable
    for key in CORE_INVARIANTS:
        assert key not in ADJUSTABLE_RANGES
        assert key not in DEFAULT_PARAMS


def test_techo_duro_de_capital_respeta_invariante():
    # El máximo del rango ajustable no puede superar el techo duro del núcleo
    _, hi = ADJUSTABLE_RANGES["capital_fraction"]
    assert hi <= CORE_INVARIANTS["max_capital_fraction_hard"]
