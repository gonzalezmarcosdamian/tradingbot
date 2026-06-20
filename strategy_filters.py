"""
strategy_filters.py — Mejoras componibles sobre la señal base de cruce.

No son estrategias nuevas: son FILTROS que se aplican sobre la señal del
cruce (SMA/EMA) para mejorar su comportamiento. Reutilizan el motor de
backtest y walk-forward ya testeados.

Cada filtro es una función pura: recibe (señal, df, params) y devuelve una
señal filtrada. Se pueden componer (encadenar varios).

Las tres mejoras tienen respaldo en la evidencia investigada:
  1. trend_filter   → reduce trades malos (solo opera a favor de la tendencia mayor)
  2. regime_filter  → evita whipsaw en mercados laterales (el asesino por fees)
  3. apply_trailing_stop → mejora el drawdown (asegura ganancia en vez de
                           devolverla esperando el cruce inverso)
"""

import numpy as np
import pandas as pd


def trend_filter(signal: pd.Series, df: pd.DataFrame, trend_ma: int = 200) -> pd.Series:
    """Solo permite estar comprado si el precio está por encima de su media
    de largo plazo (tendencia mayor alcista). Si no, fuerza a cash.
    """
    close = df["close"].reset_index(drop=True)
    signal = signal.reset_index(drop=True)
    long_ma = close.rolling(window=trend_ma, min_periods=trend_ma).mean()
    uptrend = (close > long_ma).astype(int)
    uptrend[long_ma.isna()] = 0
    return (signal & uptrend).astype(int)


def regime_filter(signal: pd.Series, df: pd.DataFrame,
                  window: int = 48, min_strength: float = 0.04) -> pd.Series:
    """Solo opera cuando el mercado tiene tendencia suficiente (no lateral).

    Mide la 'fuerza de tendencia' como el desplazamiento neto del precio
    relativo a su recorrido total en una ventana. Cercano a 0 = lateral
    (mucho ir y venir, poco avance); cercano a 1 = tendencia limpia.
    En mercado lateral, fuerza a cash para evitar whipsaw.
    """
    close = df["close"].reset_index(drop=True)
    signal = signal.reset_index(drop=True)

    # Desplazamiento neto vs recorrido absoluto acumulado (eficiencia de Kaufman)
    net_move = (close - close.shift(window)).abs()
    path = close.diff().abs().rolling(window=window, min_periods=window).sum()
    efficiency = (net_move / path).fillna(0)

    trending = (efficiency >= min_strength).astype(int)
    return (signal & trending).astype(int)


def apply_trailing_stop(signal: pd.Series, df: pd.DataFrame,
                        trail_pct: float = 0.05) -> pd.Series:
    """Aplica un trailing stop sobre la señal.

    Mientras la señal dice 'comprado', seguimos el máximo alcanzado. Si el
    precio cae trail_pct por debajo de ese máximo, forzamos salida (señal 0)
    hasta que la señal base genere una nueva entrada (nuevo bloque de 1s).

    Mejora el drawdown: asegura parte de la ganancia en vez de devolverla
    esperando el cruce inverso.
    """
    close = df["close"].reset_index(drop=True)
    signal = signal.reset_index(drop=True)
    out = signal.copy()

    in_pos = False
    peak = 0.0
    stopped_this_block = False

    for i in range(len(signal)):
        if signal.iloc[i] == 1:
            if not in_pos:
                # Nueva entrada: arranca el bloque
                in_pos = True
                peak = close.iloc[i]
                stopped_this_block = False
            else:
                peak = max(peak, close.iloc[i])

            if stopped_this_block:
                out.iloc[i] = 0  # ya saltó el stop en este bloque, quedamos fuera
            elif close.iloc[i] <= peak * (1 - trail_pct):
                out.iloc[i] = 0  # salta el trailing stop
                stopped_this_block = True
        else:
            in_pos = False
            stopped_this_block = False

    return out.astype(int)


# Registro de filtros para iterar cómodo en el runner
FILTERS = {
    "trend": trend_filter,
    "regime": regime_filter,
    "trailing": apply_trailing_stop,
}
