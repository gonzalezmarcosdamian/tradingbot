"""
test_strategy_filters.py — Tests de los filtros componibles.

Verificamos que cada filtro hace exactamente lo que promete antes de confiar
en sus resultados de backtest.
"""

import numpy as np
import pandas as pd

from strategy_filters import trend_filter, regime_filter, apply_trailing_stop


def test_trend_filter_corta_en_bajista():
    # Precio decreciente: la media de largo plazo queda por encima → fuerza cash
    close = pd.Series(np.linspace(100, 50, 300))
    df = pd.DataFrame({"close": close})
    signal = pd.Series([1] * 300)  # señal siempre "comprar"
    filtered = trend_filter(signal, df, trend_ma=200)
    # En tendencia bajista, el filtro debe mandar a cash (mayoría de ceros al final)
    assert filtered.iloc[250:].sum() == 0


def test_trend_filter_permite_en_alcista():
    close = pd.Series(np.linspace(50, 150, 300))
    df = pd.DataFrame({"close": close})
    signal = pd.Series([1] * 300)
    filtered = trend_filter(signal, df, trend_ma=200)
    # En alza sostenida, una vez que hay media, debe permitir comprar
    assert filtered.iloc[250:].sum() > 0


def test_regime_filter_corta_en_lateral():
    # Mercado lateral: oscila sin avanzar → baja eficiencia → cash
    np.random.seed(0)
    close = pd.Series(100 + np.sin(np.linspace(0, 50, 500)) * 2
                      + np.random.normal(0, 0.3, 500))
    df = pd.DataFrame({"close": close})
    signal = pd.Series([1] * 500)
    filtered = regime_filter(signal, df, window=48, min_strength=0.1)
    # En lateral, debería filtrar mucho (la mayoría a cash)
    assert filtered.sum() < signal.sum() * 0.5


def test_regime_filter_permite_en_tendencia():
    close = pd.Series(np.linspace(100, 300, 500))  # tendencia limpia
    df = pd.DataFrame({"close": close})
    signal = pd.Series([1] * 500)
    filtered = regime_filter(signal, df, window=48, min_strength=0.1)
    # En tendencia limpia, eficiencia alta → permite operar
    assert filtered.iloc[100:].sum() > 0


def test_trailing_stop_sale_en_caida():
    # Sube a 120 y después cae fuerte: el trailing debe sacarnos
    prices = list(np.linspace(100, 120, 50)) + list(np.linspace(120, 90, 50))
    close = pd.Series(prices)
    df = pd.DataFrame({"close": close})
    signal = pd.Series([1] * 100)  # señal dice comprado todo el tiempo
    filtered = apply_trailing_stop(signal, df, trail_pct=0.05)
    # Tras la caída de >5% desde el pico (120→114), debe haber salido
    assert filtered.iloc[-1] == 0
    # Pero al principio, en plena subida, debía estar dentro
    assert filtered.iloc[40] == 1


def test_trailing_stop_no_afecta_si_no_cae():
    close = pd.Series(np.linspace(100, 200, 100))  # solo sube
    df = pd.DataFrame({"close": close})
    signal = pd.Series([1] * 100)
    filtered = apply_trailing_stop(signal, df, trail_pct=0.05)
    # Si nunca cae, nunca debería frenar
    assert filtered.sum() == 100


def test_filtros_son_componibles():
    # Aplicar dos filtros en cadena no debe romper (resultado sigue siendo 0/1)
    close = pd.Series(np.linspace(50, 150, 300))
    df = pd.DataFrame({"close": close})
    signal = pd.Series([1] * 300)
    step1 = trend_filter(signal, df, trend_ma=200)
    step2 = regime_filter(step1, df, window=48, min_strength=0.05)
    assert set(step2.unique()).issubset({0, 1})
