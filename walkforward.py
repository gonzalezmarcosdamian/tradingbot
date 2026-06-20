"""
walkforward.py — Optimización walk-forward (validación out-of-sample).

Idea:
  - Dividimos la serie en ventanas que avanzan en el tiempo.
  - En cada ventana: optimizamos los parámetros (fast, slow) SOLO con la
    porción de entrenamiento, y medimos el resultado SOLO en la porción de
    test (que el optimizador nunca vio).
  - Concatenamos los retornos de test de todas las ventanas → curva
    out-of-sample, que es la estimación honesta de performance.

Esto combate el overfitting: nunca medimos sobre datos usados para optimizar.
"""

import itertools
import numpy as np
import pandas as pd

from strategy import STRATEGIES
from backtest import run_backtest, COST_PER_SIDE, BARS_PER_YEAR


def _sharpe_of_signal(df, signal):
    """Sharpe anualizado neto de costos, para usar como función objetivo."""
    close = df["close"].reset_index(drop=True)
    signal = signal.reset_index(drop=True)
    position = signal.shift(1).fillna(0)
    market_ret = close.pct_change().fillna(0)
    strat_ret = position * market_ret
    trades = position.diff().abs().fillna(0)
    strat_ret_net = strat_ret - trades * COST_PER_SIDE
    std = strat_ret_net.std()
    if std == 0:
        return -np.inf
    return strat_ret_net.mean() / std * np.sqrt(BARS_PER_YEAR)


def optimize_params(df, strat_name, fast_range, slow_range):
    """Busca (fast, slow) que maximiza Sharpe en el set de entrenamiento."""
    strat_fn = STRATEGIES[strat_name]
    best = None
    best_sharpe = -np.inf
    for fast, slow in itertools.product(fast_range, slow_range):
        if fast >= slow:
            continue
        signal = strat_fn(df["close"], fast, slow)
        sharpe = _sharpe_of_signal(df, signal)
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best = (fast, slow)
    return best, best_sharpe


def walk_forward(
    df: pd.DataFrame,
    strat_name: str,
    fast_range,
    slow_range,
    train_bars: int,
    test_bars: int,
):
    """Ejecuta walk-forward y devuelve resultados out-of-sample concatenados.

    Returns:
        dict con: oos_returns (Series), windows (lista de detalles por ventana)
    """
    strat_fn = STRATEGIES[strat_name]
    df = df.reset_index(drop=True)
    n = len(df)

    oos_returns = []
    windows = []
    start = 0

    while start + train_bars + test_bars <= n:
        train = df.iloc[start : start + train_bars]
        test = df.iloc[start + train_bars : start + train_bars + test_bars]

        # Optimizar en train
        (best_fast, best_slow), train_sharpe = optimize_params(
            train, strat_name, fast_range, slow_range
        )

        # Aplicar parámetros fijos en test (out-of-sample)
        # Para no perder el arranque de las medias en test, calculamos la señal
        # sobre train+test y nos quedamos solo con el tramo de test.
        combined = df.iloc[start : start + train_bars + test_bars]
        signal_full = strat_fn(combined["close"], best_fast, best_slow)
        signal_test = signal_full.iloc[train_bars:]

        close_test = test["close"].reset_index(drop=True)
        sig_test = signal_test.reset_index(drop=True)
        position = sig_test.shift(1).fillna(0)
        market_ret = close_test.pct_change().fillna(0)
        strat_ret = position * market_ret
        trades = position.diff().abs().fillna(0)
        strat_ret_net = strat_ret - trades * COST_PER_SIDE

        oos_returns.append(strat_ret_net)
        windows.append(
            {
                "train_start": start,
                "test_start": start + train_bars,
                "fast": best_fast,
                "slow": best_slow,
                "train_sharpe": train_sharpe,
            }
        )

        start += test_bars  # avanzar la ventana

    if not oos_returns:
        return {"oos_returns": pd.Series(dtype=float), "windows": []}

    oos_concat = pd.concat(oos_returns, ignore_index=True)
    return {"oos_returns": oos_concat, "windows": windows}


def summarize_oos(oos_returns: pd.Series) -> dict:
    """Métricas sobre la curva out-of-sample concatenada."""
    if len(oos_returns) == 0:
        return {}
    equity = (1 + oos_returns).cumprod()
    n_bars = len(oos_returns)
    years = n_bars / BARS_PER_YEAR
    total = equity.iloc[-1] - 1
    ann = equity.iloc[-1] ** (1 / years) - 1 if years > 0 else 0
    std = oos_returns.std()
    sharpe = oos_returns.mean() / std * np.sqrt(BARS_PER_YEAR) if std > 0 else 0
    running_max = equity.cummax()
    max_dd = (equity / running_max - 1).min()
    return {
        "oos_total_return": total,
        "oos_ann_return": ann,
        "oos_sharpe": sharpe,
        "oos_max_drawdown": max_dd,
        "n_bars": n_bars,
    }
