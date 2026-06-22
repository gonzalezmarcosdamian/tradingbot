"""
Exp F — Barrido de temporalidades (1h vs 4h vs 1d).

Hipótesis (de la causa raíz): los fees matan al trading intradía. A menor
frecuencia hay menos cambios de posición → menos costo → la señal de tendencia
puede sobrevivir. Probamos el cruce SMA/EMA walk-forward en cada temporalidad,
con la anualización del Sharpe CORRECTA por timeframe.

Uso: python run_research_timeframes.py
"""

import numpy as np
import pandas as pd

from run_backtest import fetch_history
from walkforward import walk_forward

SYMBOL = "BTC/USDT"
FAST = range(10, 51, 5)
SLOW = range(50, 201, 10)
TRAIN_DAYS = 365
TEST_DAYS = 90

# (timeframe, barras/año, barras/día, días de historia a bajar)
TFS = [
    ("1h", 24 * 365, 24, 730),
    ("4h", 6 * 365, 6, 900),
    ("1d", 365, 1, 1500),
]


def metrics(oos: pd.Series, bpy: int) -> dict:
    if len(oos) == 0:
        return {"ret": 0, "sharpe": 0, "maxdd": 0}
    eq = (1 + oos).cumprod()
    sd = oos.std()
    return {
        "ret": eq.iloc[-1] - 1,
        "sharpe": oos.mean() / sd * np.sqrt(bpy) if sd else 0,
        "maxdd": (eq / eq.cummax() - 1).min(),
    }


def bh_metrics(df: pd.DataFrame, bpy: int) -> dict:
    r = df["close"].pct_change().fillna(0)
    eq = (1 + r).cumprod()
    return {"ret": eq.iloc[-1] - 1,
            "sharpe": r.mean() / r.std() * np.sqrt(bpy) if r.std() else 0,
            "maxdd": (eq / eq.cummax() - 1).min()}


def pct(x):
    return f"{x*100:+.1f}%"


def main():
    print("=" * 70)
    print("EXP F — Cruce SMA/EMA por temporalidad (walk-forward OOS)")
    print("=" * 70)
    print(f"{'TF':<5}{'estrategia':<12}{'ret OOS':>10}{'Sharpe':>9}{'maxDD':>9}"
          f"{'B&H Sharpe':>12}{'gana?':>8}")
    print("-" * 70)

    winners = []
    for tf, bpy, per_day, days in TFS:
        df = fetch_history(SYMBOL, tf, days)
        train = TRAIN_DAYS * per_day
        test = TEST_DAYS * per_day
        bh = bh_metrics(df, bpy)
        for strat in ("SMA", "EMA"):
            wf = walk_forward(df, strat, FAST, SLOW, train, test)
            m = metrics(wf["oos_returns"], bpy)
            gana = m["sharpe"] > bh["sharpe"] and m["maxdd"] > bh["maxdd"]
            if gana:
                winners.append((tf, strat, m["sharpe"]))
            print(f"{tf:<5}{strat:<12}{pct(m['ret']):>10}{m['sharpe']:>9.2f}"
                  f"{pct(m['maxdd']):>9}{bh['sharpe']:>12.2f}{('SÍ' if gana else 'no'):>8}")
        print("-" * 70)

    print("=" * 70)
    if winners:
        print("-> Temporalidades donde el cruce SUPERA al B&H:")
        for tf, s, sh in winners:
            print(f"   {tf} {s}: Sharpe {sh:.2f}  -> candidato real, vale profundizar")
    else:
        print("-> En ninguna temporalidad el cruce supera al B&H (Sharpe Y drawdown).")


if __name__ == "__main__":
    main()
