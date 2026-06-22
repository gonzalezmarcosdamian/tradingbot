"""
Exp F-bis — Validación del cruce SMA diario sobre toda la historia, por año.

El SMA diario le ganó al B&H sobre 4 años, pero perdió en el período reciente.
¿Es un edge cíclico (gana en bull, pierde en lateral) o suerte? Acá corremos
walk-forward sobre la máxima historia y desglosamos el retorno OOS por año
calendario, comparado con buy & hold.

Uso: python run_research_daily_validate.py
"""

import numpy as np
import pandas as pd

from run_backtest import fetch_history
from walkforward import optimize_params
from strategy import sma_signal
from backtest import COST_PER_SIDE

SYMBOL = "BTC/USDT"
FAST = range(10, 51, 5)
SLOW = range(50, 201, 10)
TRAIN = 365
TEST = 90
DAYS = 3000   # ~8 años (Binance BTC/USDT desde ~2017)


def main():
    df = fetch_history(SYMBOL, "1d", DAYS)
    df = df.reset_index(drop=True)
    n = len(df)
    print(f"{n} días ({df['timestamp'].iloc[0].date()} → {df['timestamp'].iloc[-1].date()})\n")

    net_parts = []
    start = 0
    while start + TRAIN + TEST <= n:
        train = df.iloc[start:start + TRAIN]
        (bf, bs), _ = optimize_params(train, "SMA", FAST, SLOW)
        comb = df.iloc[start:start + TRAIN + TEST]
        sig = sma_signal(comb["close"], bf, bs).reset_index(drop=True).astype(int)
        sig_test = sig.iloc[TRAIN:].reset_index(drop=True)
        test = df.iloc[start + TRAIN:start + TRAIN + TEST].reset_index(drop=True)
        pos = sig_test.shift(1).fillna(0)
        ret = test["close"].pct_change().fillna(0)
        net = pos * ret - pos.diff().abs().fillna(0) * COST_PER_SIDE
        part = pd.DataFrame({"ts": test["timestamp"], "strat": net,
                             "bh": ret})
        net_parts.append(part)
        start += TEST

    allr = pd.concat(net_parts, ignore_index=True)
    allr["year"] = pd.to_datetime(allr["ts"]).dt.year

    print("=" * 52)
    print("SMA diario (OOS) vs Buy & Hold — retorno por año")
    print("=" * 52)
    print(f"{'año':<8}{'SMA-1d':>12}{'B&H':>12}{'mejor':>10}")
    print("-" * 52)
    for year, g in allr.groupby("year"):
        s = (1 + g["strat"]).prod() - 1
        b = (1 + g["bh"]).prod() - 1
        print(f"{year:<8}{s*100:>11.1f}%{b*100:>11.1f}%{('SMA' if s > b else 'B&H'):>10}")
    print("-" * 52)
    s_tot = (1 + allr["strat"]).prod() - 1
    b_tot = (1 + allr["bh"]).prod() - 1
    s_sh = allr["strat"].mean() / allr["strat"].std() * np.sqrt(365)
    b_sh = allr["bh"].mean() / allr["bh"].std() * np.sqrt(365)
    s_eq = (1 + allr["strat"]).cumprod(); b_eq = (1 + allr["bh"]).cumprod()
    s_dd = (s_eq / s_eq.cummax() - 1).min(); b_dd = (b_eq / b_eq.cummax() - 1).min()
    print(f"{'TOTAL':<8}{s_tot*100:>11.0f}%{b_tot*100:>11.0f}%")
    print(f"{'Sharpe':<8}{s_sh:>12.2f}{b_sh:>12.2f}")
    print(f"{'maxDD':<8}{s_dd*100:>11.0f}%{b_dd*100:>11.0f}%")
    print("=" * 52)
    wins = sum(1 for _, g in allr.groupby("year")
               if (1 + g["strat"]).prod() > (1 + g["bh"]).prod())
    total_years = allr["year"].nunique()
    print(f"Años donde SMA-1d gana: {wins}/{total_years}")


if __name__ == "__main__":
    main()
