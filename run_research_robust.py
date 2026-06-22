"""
Exp G — Robustez del trend-following diario: varios activos × params FIJOS.

Para confiar en el edge hay que descartar dos trampas:
  1. Que funcione solo en BTC (suerte de un activo).
  2. Que dependa de parámetros sobre-optimizados.

Por eso: cruce SMA diario con parámetros FIJOS (sin optimizar) sobre varios
activos, comparado vs Buy & Hold. Params fijos = no hay sobre-ajuste posible.

Uso: python run_research_robust.py
"""

import numpy as np

from run_backtest import fetch_history
from strategy import sma_signal
from backtest import COST_PER_SIDE

ASSETS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]
PARAMS = [(10, 50), (20, 50), (20, 100), (50, 100), (50, 200), (100, 200)]
DAYS = 3000
BPY = 365


def daily_bt(close, fast, slow):
    sig = sma_signal(close, fast, slow).astype(int)
    pos = sig.shift(1).fillna(0)
    ret = close.pct_change().fillna(0)
    net = pos * ret - pos.diff().abs().fillna(0) * COST_PER_SIDE
    eq = (1 + net).cumprod()
    sd = net.std()
    return {"sharpe": net.mean() / sd * np.sqrt(BPY) if sd else 0,
            "ret": eq.iloc[-1] - 1,
            "maxdd": (eq / eq.cummax() - 1).min()}


def bh(close):
    r = close.pct_change().fillna(0)
    eq = (1 + r).cumprod()
    return {"sharpe": r.mean() / r.std() * np.sqrt(BPY) if r.std() else 0,
            "ret": eq.iloc[-1] - 1,
            "maxdd": (eq / eq.cummax() - 1).min()}


def main():
    wins = {p: 0 for p in PARAMS}
    sharpes = {p: [] for p in PARAMS}
    print("=" * 72)
    print("EXP G — SMA diario, params FIJOS, varios activos (vs Buy & Hold)")
    print("=" * 72)
    for asset in ASSETS:
        try:
            df = fetch_history(asset, "1d", DAYS)
        except Exception as e:
            print(f"{asset}: error {e}"); continue
        close = df["close"]
        b = bh(close)
        print(f"\n{asset}  ({len(df)}d)  B&H: Sharpe {b['sharpe']:.2f}  "
              f"ret {b['ret']*100:+.0f}%  maxDD {b['maxdd']*100:.0f}%")
        print(f"  {'params':<12}{'Sharpe':>8}{'ret':>9}{'maxDD':>8}{'vs B&H':>9}")
        for p in PARAMS:
            m = daily_bt(close, *p)
            gana = m["sharpe"] > b["sharpe"] and m["maxdd"] > b["maxdd"]
            wins[p] += 1 if gana else 0
            sharpes[p].append(m["sharpe"])
            mark = "GANA" if gana else ""
            print(f"  {str(p):<12}{m['sharpe']:>8.2f}{m['ret']*100:>8.0f}%"
                  f"{m['maxdd']*100:>7.0f}%{mark:>9}")

    print("\n" + "=" * 72)
    print("RESUMEN por parámetro (cuántos activos gana al B&H, y Sharpe promedio):")
    print("-" * 72)
    ranked = sorted(PARAMS, key=lambda p: np.mean(sharpes[p]), reverse=True)
    for p in ranked:
        avg = np.mean(sharpes[p]) if sharpes[p] else 0
        print(f"  {str(p):<12} gana {wins[p]}/{len(ASSETS)} activos   Sharpe prom {avg:+.2f}")
    print("=" * 72)
    best = ranked[0]
    print(f"-> Parámetro más robusto: {best} (Sharpe prom {np.mean(sharpes[best]):+.2f}, "
          f"gana {wins[best]}/{len(ASSETS)})")


if __name__ == "__main__":
    main()
