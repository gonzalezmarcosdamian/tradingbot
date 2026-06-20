"""
signals_research.py — Familias de señales para buscar edge (research, etapa 2).

El cruce de medias (strategy.py) no mostró edge en BTC. Acá probamos enfoques
distintos, todos long-only y anti look-ahead (la señal en t usa datos hasta t;
el backtester ejecuta en t+1 con shift):

  - RSI mean-reversion: comprar sobrevendido, salir al normalizar.
  - Bollinger mean-reversion: comprar bajo la banda inferior, salir en la media.
  - Donchian breakout: comprar al romper máximos, salir al perder el canal.
  - Momentum (time-series): comprar si el retorno del lookback es positivo.

Todas las señales son funciones PURAS sobre precios → testeables sin red.
Convención de salida: Series de int {0,1} (1 = querer estar comprado).
"""

import numpy as np
import pandas as pd


# ── Indicadores base ───────────────────────────────────────────────

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI clásico (media simple de ganancias/pérdidas). NaN hasta tener
    `period` datos."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    # Si no hubo pérdidas (avg_loss=0) el RSI es 100 (todo ganancia).
    out[avg_loss == 0] = 100.0
    return out


def _hold_between(entries: pd.Series, exits: pd.Series, index) -> pd.Series:
    """Construye una señal long-only con estado: 1 desde una entrada hasta la
    próxima salida. Vectorizado vía forward-fill, sin look-ahead."""
    sig = pd.Series(np.nan, index=index)
    sig[entries] = 1.0
    sig[exits] = 0.0
    return sig.ffill().fillna(0).astype(int)


# ── Estrategias ────────────────────────────────────────────────────

def rsi_reversion_signal(close: pd.Series, period: int = 14,
                         oversold: float = 30, exit_level: float = 55) -> pd.Series:
    """Mean-reversion por RSI: entra cuando el RSI cae bajo `oversold`, sale
    cuando supera `exit_level`."""
    r = rsi(close, period)
    return _hold_between(r < oversold, r > exit_level, close.index)


def bollinger_reversion_signal(close: pd.Series, window: int = 20,
                               k: float = 2.0) -> pd.Series:
    """Mean-reversion por Bandas de Bollinger: entra cuando el precio cae bajo
    la banda inferior (media - k·desvío), sale cuando vuelve a la media."""
    ma = close.rolling(window, min_periods=window).mean()
    sd = close.rolling(window, min_periods=window).std()
    lower = ma - k * sd
    return _hold_between(close < lower, close >= ma, close.index)


def donchian_breakout_signal(df: pd.DataFrame, entry_n: int = 20,
                             exit_n: int = 10) -> pd.Series:
    """Breakout de canal Donchian: entra al superar el máximo de las `entry_n`
    velas PREVIAS, sale al perforar el mínimo de las `exit_n` previas.

    Usa high/low desplazados (shift 1): el canal no incluye la vela actual, así
    la ruptura se mide contra el pasado (sin look-ahead)."""
    high, low, close = df["high"], df["low"], df["close"]
    upper = high.shift(1).rolling(entry_n, min_periods=entry_n).max()
    lower = low.shift(1).rolling(exit_n, min_periods=exit_n).min()
    return _hold_between(close > upper, close < lower, close.index)


def momentum_signal(close: pd.Series, lookback: int = 168) -> pd.Series:
    """Momentum time-series: comprado si el precio está por encima del de hace
    `lookback` velas (retorno del período positivo). `lookback` en velas
    (168 = 7 días en 1h)."""
    past = close.shift(lookback)
    sig = (close > past).astype(int)
    sig[past.isna()] = 0
    return sig
