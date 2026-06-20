"""
strategy.py — Generación de señales de cruce de medias (SMA y EMA).

Diseño anti look-ahead:
  - Las medias se calculan sobre el precio de cierre hasta la vela t.
  - La señal de la vela t se EJECUTA en la apertura de la vela t+1
    (lo maneja el backtester con un shift). Acá solo generamos la señal.

Señal long-only:
  - 1 = querer estar comprado (corta cruzó arriba de la larga)
  - 0 = querer estar en cash (corta cruzó abajo)
"""

import pandas as pd


def sma_signal(close: pd.Series, fast: int, slow: int) -> pd.Series:
    """Señal de cruce de medias simples (SMA)."""
    fast_ma = close.rolling(window=fast, min_periods=fast).mean()
    slow_ma = close.rolling(window=slow, min_periods=slow).mean()
    # 1 cuando la rápida está por encima de la lenta, 0 si no
    signal = (fast_ma > slow_ma).astype(int)
    # Las primeras velas sin media completa quedan en 0 (cash)
    signal[slow_ma.isna()] = 0
    return signal


def ema_signal(close: pd.Series, fast: int, slow: int) -> pd.Series:
    """Señal de cruce de medias exponenciales (EMA)."""
    fast_ma = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ma = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    signal = (fast_ma > slow_ma).astype(int)
    signal[slow_ma.isna()] = 0
    return signal


# Registro de estrategias disponibles para iterar cómodo
STRATEGIES = {
    "SMA": sma_signal,
    "EMA": ema_signal,
}
