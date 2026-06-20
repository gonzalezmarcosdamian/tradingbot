"""
research_wf.py — Walk-forward genérico para evaluar estrategias arbitrarias.

walkforward.py optimiza solo (fast, slow) del cruce de medias. Para investigar
otras familias (RSI, Bollinger, Donchian, momentum) necesitamos optimizar sobre
una grilla de parámetros cualquiera. Este módulo generaliza el walk-forward:

  - El llamador pasa un `signal_builder(df_slice, params) -> Series 0/1` y una
    lista de `param_grid` (cada item es un dict de parámetros).
  - En cada ventana se elige, SOLO en train, la combinación de mayor Sharpe; se
    mide SOLO en test (out-of-sample). Mismo criterio anti-overfitting que
    walkforward.py, mismo modelo de costos.

Devuelve los retornos OOS concatenados y los parámetros elegidos por ventana
(para auditar estabilidad).
"""

from typing import Callable

import numpy as np
import pandas as pd

from backtest import COST_PER_SIDE, BARS_PER_YEAR
from walkforward import _sharpe_of_signal


SignalBuilder = Callable[[pd.DataFrame, dict], pd.Series]


def generic_walk_forward(
    df: pd.DataFrame,
    signal_builder: SignalBuilder,
    param_grid: list,
    train_bars: int,
    test_bars: int,
) -> dict:
    """Walk-forward optimizando sobre `param_grid`. Devuelve dict con
    oos_returns (Series) y chosen (params por ventana)."""
    df = df.reset_index(drop=True)
    n = len(df)
    oos_returns = []
    chosen = []
    start = 0

    while start + train_bars + test_bars <= n:
        train = df.iloc[start : start + train_bars]

        # Optimizar en train
        best, best_sharpe = None, -np.inf
        for params in param_grid:
            sig = signal_builder(train, params)
            sharpe = _sharpe_of_signal(train, sig)
            if sharpe > best_sharpe:
                best_sharpe, best = sharpe, params

        # Medir en test con los params fijos. Calculamos la señal sobre
        # train+test para warm-up de los indicadores y tomamos solo el test.
        combined = df.iloc[start : start + train_bars + test_bars]
        sig_full = signal_builder(combined, best)
        sig_test = sig_full.iloc[train_bars:].reset_index(drop=True)
        close_test = df["close"].iloc[start + train_bars : start + train_bars + test_bars].reset_index(drop=True)

        position = sig_test.shift(1).fillna(0)
        market_ret = close_test.pct_change().fillna(0)
        net = position * market_ret - position.diff().abs().fillna(0) * COST_PER_SIDE

        oos_returns.append(net)
        chosen.append(best)
        start += test_bars

    if not oos_returns:
        return {"oos_returns": pd.Series(dtype=float), "chosen": []}

    return {"oos_returns": pd.concat(oos_returns, ignore_index=True), "chosen": chosen}


def oos_metrics(oos_returns: pd.Series) -> dict:
    """Métricas honestas sobre la curva OOS concatenada."""
    if len(oos_returns) == 0:
        return {}
    equity = (1 + oos_returns).cumprod()
    years = len(oos_returns) / BARS_PER_YEAR
    std = oos_returns.std()
    return {
        "ret": equity.iloc[-1] - 1,
        "ann": equity.iloc[-1] ** (1 / years) - 1 if years > 0 else 0,
        "sharpe": oos_returns.mean() / std * np.sqrt(BARS_PER_YEAR) if std > 0 else 0,
        "maxdd": (equity / equity.cummax() - 1).min(),
        "exposure": (oos_returns != 0).mean(),
    }
