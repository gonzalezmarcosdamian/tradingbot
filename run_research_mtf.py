"""
run_research_mtf.py — Experimento: cruce 1h confirmado por tendencia 4h.

Hipótesis: filtrar la señal de cruce de 1h para operar SOLO cuando el marco de
4h está en tendencia alcista reduce trades malos (whipsaw) y mejora el OOS.

Método (sin look-ahead):
  - Optimiza fast/slow del cruce SMA en train (igual que walkforward.py).
  - La tendencia de 4h se calcula con la barra de 4h YA CERRADA (shift) y se
    proyecta sobre las velas de 1h (ffill).
  - Mide out-of-sample base (sin filtro) vs +4h, con el mismo modelo de costos.

Uso:
  python run_research_mtf.py
"""

import numpy as np
import pandas as pd

from run_backtest import fetch_history
from strategy import sma_signal
from backtest import COST_PER_SIDE, BARS_PER_YEAR
from walkforward import optimize_params, summarize_oos

SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"
DAYS = 730
FAST = range(10, 51, 5)
SLOW = range(50, 201, 10)
TRAIN = 24 * 180
TEST = 24 * 60
MA4_PERIODS = 50          # SMA de 4h (50 barras ≈ 8 días)


def trend_4h(df: pd.DataFrame) -> np.ndarray:
    """Tendencia 4h (1=alcista) proyectada a la grilla de 1h, sin look-ahead."""
    s = df.set_index("timestamp")["close"]
    c4 = s.resample("4h").last()
    sma4 = c4.rolling(MA4_PERIODS, min_periods=MA4_PERIODS).mean()
    t4 = (c4 > sma4).astype(float).shift(1)        # barra 4h previa (ya cerrada)
    t1 = t4.reindex(s.index, method="ffill").fillna(0)
    return t1.to_numpy()


def _oos_net(signal: pd.Series, close_test: pd.Series) -> pd.Series:
    pos = signal.shift(1).fillna(0)
    ret = close_test.pct_change().fillna(0)
    return pos * ret - pos.diff().abs().fillna(0) * COST_PER_SIDE


def main():
    df = fetch_history(SYMBOL, TIMEFRAME, DAYS)
    trend = trend_4h(df)
    n = len(df)

    oos_base, oos_mtf = [], []
    start = 0
    while start + TRAIN + TEST <= n:
        train = df.iloc[start:start + TRAIN]
        (bf, bs), _ = optimize_params(train, "SMA", FAST, SLOW)

        comb = df.iloc[start:start + TRAIN + TEST]
        base = sma_signal(comb["close"], bf, bs).reset_index(drop=True).astype(int)
        tr = pd.Series(trend[start:start + TRAIN + TEST]).reset_index(drop=True).astype(int)
        mtf = (base & tr)

        close_test = df["close"].iloc[start + TRAIN:start + TRAIN + TEST].reset_index(drop=True)
        oos_base.append(_oos_net(base.iloc[TRAIN:].reset_index(drop=True), close_test))
        oos_mtf.append(_oos_net(mtf.iloc[TRAIN:].reset_index(drop=True), close_test))
        start += TEST

    base_oos = pd.concat(oos_base, ignore_index=True)
    mtf_oos = pd.concat(oos_mtf, ignore_index=True)
    b, m = summarize_oos(base_oos), summarize_oos(mtf_oos)

    bh = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    bh_ret = df["close"].pct_change().fillna(0)
    bh_sharpe = bh_ret.mean() / bh_ret.std() * np.sqrt(BARS_PER_YEAR) if bh_ret.std() else 0

    print("\n" + "=" * 60)
    print(f"EXPERIMENTO MTF — cruce 1h vs cruce 1h + tendencia 4h")
    print(f"Buy & Hold: ret {bh*100:+.1f}%  Sharpe {bh_sharpe:.2f}")
    print("=" * 60)
    print(f"{'variante':<22}{'ret OOS':>10}{'Sharpe':>9}{'maxDD':>9}")
    print("-" * 60)
    print(f"{'cruce 1h (base)':<22}{b['oos_total_return']*100:>9.1f}%"
          f"{b['oos_sharpe']:>9.2f}{b['oos_max_drawdown']*100:>8.1f}%")
    print(f"{'1h + tendencia 4h':<22}{m['oos_total_return']*100:>9.1f}%"
          f"{m['oos_sharpe']:>9.2f}{m['oos_max_drawdown']*100:>8.1f}%")
    print("=" * 60)
    better = m["oos_sharpe"] > b["oos_sharpe"] and m["oos_max_drawdown"] > b["oos_max_drawdown"]
    if better and m["oos_sharpe"] > bh_sharpe:
        print("-> El filtro 4h mejora Y supera al B&H: candidato a seguir.")
    elif better:
        print("-> El filtro 4h mejora la base, pero sigue sin superar al B&H.")
    else:
        print("-> El filtro 4h NO mejora de forma clara.")


if __name__ == "__main__":
    main()
