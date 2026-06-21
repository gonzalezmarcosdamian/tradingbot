"""
Exp A — Volatility breakout (Keltner) + filtro de régimen.

Idea: entrar long cuando el precio rompe la banda superior (MA + k·ATR) — una
ruptura ajustada por volatilidad — y salir al volver a la MA. Opcionalmente
operar solo en régimen de alta volatilidad (ATR% sobre su mediana), para evitar
el whipsaw del lateral. Backtest 2 años, params fijos.

Uso: python run_research_breakout.py
"""

import numpy as np
import pandas as pd

from run_backtest import fetch_history
from backtest import run_backtest

SYMBOL, TIMEFRAME, DAYS = "BTC/USDT", "1h", 730


def atr(df, period=24):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def hold_between(entries, exits, index):
    s = pd.Series(np.nan, index=index)
    s[entries] = 1.0
    s[exits] = 0.0
    return s.ffill().fillna(0).astype(int)


def keltner_signal(df, ma_n=48, k=1.5, atr_n=24, vol_filter=False):
    c = df["close"]
    ma = c.rolling(ma_n, min_periods=ma_n).mean()
    a = atr(df, atr_n)
    upper = ma + k * a
    entries = c > upper
    exits = c < ma
    sig = hold_between(entries, exits, c.index)
    if vol_filter:
        atr_pct = a / c
        high_vol = atr_pct > atr_pct.rolling(ma_n, min_periods=ma_n).median()
        sig = (sig & high_vol.fillna(False).astype(int))
    return sig


def pct(x):
    return f"{x*100:+.1f}%"


def main():
    df = fetch_history(SYMBOL, TIMEFRAME, DAYS)
    m0 = run_backtest(df, keltner_signal(df, 48, 1.5))
    print("\n" + "=" * 62)
    print(f"EXP A — Volatility breakout (Keltner) — {SYMBOL} 2 años")
    print(f"Buy & Hold: ret {pct(m0['bh_return'])}  Sharpe {m0['bh_sharpe']:.2f}  "
          f"maxDD {pct(m0['bh_max_drawdown'])}")
    print("=" * 62)
    print(f"{'variante':<28}{'ret':>10}{'Sharpe':>8}{'maxDD':>9}")
    print("-" * 62)
    best = (None, -9)
    for k in (1.0, 1.5, 2.0, 2.5):
        for vf in (False, True):
            sig = keltner_signal(df, 48, k, 24, vf)
            m = run_backtest(df, sig)
            name = f"Keltner k={k}{' +volfilt' if vf else ''}"
            print(f"{name:<28}{pct(m['total_return']):>10}{m['sharpe']:>8.2f}{pct(m['max_drawdown']):>9}")
            if m["sharpe"] > best[1]:
                best = (name, m["sharpe"], m)
    print("=" * 62)
    bm = best[2]
    if best[1] > m0["bh_sharpe"] and bm["max_drawdown"] > m0["bh_max_drawdown"]:
        print(f"-> Mejor '{best[0]}' SUPERA al B&H (Sharpe {best[1]:.2f}). Vale walk-forward.")
    else:
        print(f"-> Mejor '{best[0]}' Sharpe {best[1]:.2f}: NO supera al B&H.")


if __name__ == "__main__":
    main()
