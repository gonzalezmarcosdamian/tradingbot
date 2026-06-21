"""
run_research_ensemble.py — Experimento 3: ensamble de señales por voto.

Hipótesis: combinar varias señales de tendencia (cruce SMA + breakout Donchian +
momentum) por VOTO reduce el ruido de cada una y mejora el resultado vs usar una
sola. Se prueba con parámetros fijos razonables sobre 2 años de data real.

Es un primer corte (backtest de período completo, params fijos → sin
sobre-optimización). Si una variante promete, recién ahí vale el walk-forward.

Uso:
  python run_research_ensemble.py
"""

import pandas as pd

from run_backtest import fetch_history
from strategy import sma_signal
from signals_research import donchian_breakout_signal, momentum_signal
from backtest import run_backtest

SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"
DAYS = 730


def pct(x):
    return f"{x*100:+.1f}%"


def row(name, m):
    print(f"{name:<24}{pct(m['total_return']):>10}{m['sharpe']:>8.2f}"
          f"{pct(m['max_drawdown']):>9}{pct(m['exposure']):>9}")


def main():
    df = fetch_history(SYMBOL, TIMEFRAME, DAYS)
    close = df["close"]

    # Señales componentes (params fijos razonables), todas de tendencia
    s_sma = sma_signal(close, 20, 50)
    s_don = donchian_breakout_signal(df, 20, 10)
    s_mom = momentum_signal(close, 168)  # 7 días
    components = {"SMA(20,50)": s_sma, "Donchian(20,10)": s_don, "Momentum(168)": s_mom}

    votes = (s_sma.astype(int) + s_don.astype(int) + s_mom.astype(int))
    ens_any = (votes >= 1).astype(int)   # alguna dice long
    ens_maj = (votes >= 2).astype(int)   # mayoría
    ens_all = (votes >= 3).astype(int)   # todas

    m0 = run_backtest(df, s_sma)
    print("\n" + "=" * 62)
    print(f"EXPERIMENTO ENSAMBLE — {SYMBOL}, 2 años")
    print(f"Buy & Hold: ret {pct(m0['bh_return'])}  Sharpe {m0['bh_sharpe']:.2f}  "
          f"maxDD {pct(m0['bh_max_drawdown'])}")
    print("=" * 62)
    print(f"{'variante':<24}{'ret':>10}{'Sharpe':>8}{'maxDD':>9}{'expos.':>9}")
    print("-" * 62)
    for name, sig in components.items():
        row(name, run_backtest(df, sig))
    print("-" * 62)
    row("Ensamble (>=1)", run_backtest(df, ens_any))
    row("Ensamble (mayoría>=2)", run_backtest(df, ens_maj))
    row("Ensamble (todas=3)", run_backtest(df, ens_all))
    print("=" * 62)
    best = max([("any", run_backtest(df, ens_any)),
                ("maj", run_backtest(df, ens_maj)),
                ("all", run_backtest(df, ens_all))], key=lambda x: x[1]["sharpe"])
    if best[1]["sharpe"] > m0["bh_sharpe"] and best[1]["max_drawdown"] > m0["bh_max_drawdown"]:
        print(f"-> El ensamble '{best[0]}' supera al B&H: vale walk-forward.")
    else:
        print("-> Ningún ensamble supera al B&H (Sharpe Y drawdown).")


if __name__ == "__main__":
    main()
