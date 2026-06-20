"""
test_signals_research.py — Tests de las señales de research.

Verifican: límites del RSI, lógica de entrada/salida con estado (forward-fill),
breakout Donchian contra el pasado (sin look-ahead) y momentum. Datos
sintéticos: precisos y sin red.
"""

import numpy as np
import pandas as pd

from research_wf import generic_walk_forward, oos_metrics
from signals_research import (
    rsi,
    rsi_reversion_signal,
    bollinger_reversion_signal,
    donchian_breakout_signal,
    momentum_signal,
)


# ── RSI ────────────────────────────────────────────────────────────

def test_rsi_sube_monotono_da_100():
    close = pd.Series(np.arange(1, 30, dtype="float64"))  # estrictamente creciente
    r = rsi(close, period=14)
    assert r.dropna().iloc[-1] == 100.0  # sin pérdidas → RSI 100


def test_rsi_en_rango_0_100():
    rng = np.random.default_rng(0)
    close = pd.Series(100 + rng.standard_normal(200).cumsum())
    r = rsi(close, 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


# ── RSI reversion ──────────────────────────────────────────────────

def test_rsi_reversion_entra_en_sobreventa():
    # Caída sostenida → RSI muy bajo → entra y queda comprado en el piso.
    close = pd.Series([100, 98, 96, 94, 92, 90, 88, 86, 84, 82])
    sig = rsi_reversion_signal(close, period=3, oversold=30, exit_level=70)
    assert sig.iloc[-1] == 1  # entró en sobreventa y sigue comprado


def test_rsi_reversion_sale_al_normalizar():
    # Caída (entra) y luego rally fuerte → RSI supera el exit → sale.
    close = pd.Series([100, 98, 96, 94, 92, 90, 95, 100, 105, 110])
    sig = rsi_reversion_signal(close, period=3, oversold=30, exit_level=70)
    assert sig.iloc[-1] == 0  # el rally llevó el RSI sobre el exit → fuera


def test_rsi_reversion_es_binaria():
    rng = np.random.default_rng(1)
    close = pd.Series(100 + rng.standard_normal(300).cumsum())
    sig = rsi_reversion_signal(close, 14, 30, 55)
    assert set(sig.unique()).issubset({0, 1})


# ── Bollinger reversion ────────────────────────────────────────────

def test_bollinger_entra_bajo_banda_inferior():
    # Serie estable y un desplome puntual que perfora la banda inferior.
    close = pd.Series([100] * 25 + [80])
    sig = bollinger_reversion_signal(close, window=20, k=2.0)
    assert sig.iloc[-1] == 1


# ── Donchian breakout ──────────────────────────────────────────────

def test_donchian_entra_al_romper_maximos():
    n = 30
    df = pd.DataFrame({
        "high": [100] * n + [120],
        "low": [90] * n + [110],
        "close": [95] * n + [119],  # cierre rompe el máximo previo (100)
    })
    sig = donchian_breakout_signal(df, entry_n=20, exit_n=10)
    assert sig.iloc[-1] == 1


def test_donchian_sin_lookahead_usa_canal_previo():
    # Cierre plano: nunca supera el máximo de las velas previas → siempre 0.
    df = pd.DataFrame({"high": [100] * 40, "low": [100] * 40, "close": [100] * 40})
    sig = donchian_breakout_signal(df, 20, 10)
    assert (sig == 0).all()


# ── Momentum ───────────────────────────────────────────────────────

def test_momentum_largo_si_sube():
    close = pd.Series(np.arange(1, 100, dtype="float64"))  # creciente
    sig = momentum_signal(close, lookback=10)
    assert sig.iloc[-1] == 1


def test_momentum_fuera_si_baja():
    close = pd.Series(np.arange(100, 1, -1, dtype="float64"))  # decreciente
    sig = momentum_signal(close, lookback=10)
    assert sig.iloc[-1] == 0


# ── Walk-forward genérico ──────────────────────────────────────────

def test_generic_walk_forward_devuelve_oos_y_chosen():
    rng = np.random.default_rng(7)
    close = pd.Series(100 + rng.standard_normal(900).cumsum() + 100)
    df = pd.DataFrame({"close": close.abs() + 1})
    builder = lambda d, p: momentum_signal(d["close"], p["lookback"])
    param_grid = [{"lookback": 24}, {"lookback": 48}]
    wf = generic_walk_forward(df, builder, param_grid, train_bars=400, test_bars=200)
    assert len(wf["oos_returns"]) > 0
    assert len(wf["chosen"]) >= 1
    m = oos_metrics(wf["oos_returns"])
    assert "sharpe" in m and "maxdd" in m
