"""
Exp H — Mejoras sobre la base validada (SMA 20/50 diario).

El punto débil del trend-following son los drawdowns. Probamos un TRAILING STOP
sobre la señal diaria (cortar cuando el precio cae X% desde el máximo de la
posición, antes de esperar el cruce inverso) en los 4 activos. Objetivo: bajar
el drawdown sin destruir el Sharpe.

Uso: python run_research_improve.py
"""

import numpy as np

from run_backtest import fetch_history
from strategy import sma_signal
from strategy_filters import apply_trailing_stop
from backtest import COST_PER_SIDE

ASSETS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]
FAST, SLOW = 20, 50
TRAILS = [None, 0.15, 0.20, 0.25]
DAYS = 3000
BPY = 365


def bt(close, signal):
    pos = signal.shift(1).fillna(0)
    ret = close.pct_change().fillna(0)
    net = pos * ret - pos.diff().abs().fillna(0) * COST_PER_SIDE
    eq = (1 + net).cumprod()
    sd = net.std()
    return {"sharpe": net.mean() / sd * np.sqrt(BPY) if sd else 0,
            "ret": eq.iloc[-1] - 1,
            "maxdd": (eq / eq.cummax() - 1).min()}


def main():
    agg = {t: {"sharpe": [], "maxdd": []} for t in TRAILS}
    print("=" * 70)
    print("EXP H — SMA 20/50 diario + trailing stop (4 activos)")
    print("=" * 70)
    for asset in ASSETS:
        df = fetch_history(asset, "1d", DAYS)
        close = df["close"]
        base = sma_signal(close, FAST, SLOW).astype(int)
        print(f"\n{asset} ({len(df)}d)")
        print(f"  {'variante':<18}{'Sharpe':>8}{'ret':>9}{'maxDD':>8}")
        for t in TRAILS:
            sig = base if t is None else apply_trailing_stop(base, df, t)
            m = bt(close, sig)
            agg[t]["sharpe"].append(m["sharpe"])
            agg[t]["maxdd"].append(m["maxdd"])
            name = "base (sin stop)" if t is None else f"trailing {int(t*100)}%"
            print(f"  {name:<18}{m['sharpe']:>8.2f}{m['ret']*100:>8.0f}%{m['maxdd']*100:>7.0f}%")

    print("\n" + "=" * 70)
    print("PROMEDIO por variante (4 activos):")
    print(f"  {'variante':<18}{'Sharpe prom':>12}{'maxDD prom':>12}")
    for t in TRAILS:
        name = "base" if t is None else f"trailing {int(t*100)}%"
        print(f"  {name:<18}{np.mean(agg[t]['sharpe']):>12.2f}{np.mean(agg[t]['maxdd'])*100:>11.0f}%")
    print("=" * 70)


if __name__ == "__main__":
    main()
