"""
Exp I — Portfolio multi-activo de trend-following diario.

La forma clásica de bajar el drawdown del trend-following es DIVERSIFICAR entre
sleeves, no poner stops. Cada activo lleva su señal SMA 20/50; el capital se
reparte equitativamente entre los que están "long". Si ninguno está en
tendencia, el portfolio queda en cash.

Hipótesis: Sharpe similar/mejor y drawdown MENOR que un solo activo.

Uso: python run_research_portfolio.py
"""

import numpy as np
import pandas as pd

from run_backtest import fetch_history
from strategy import sma_signal
from backtest import COST_PER_SIDE

ASSETS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]
FAST, SLOW = 20, 50
DAYS = 3000
BPY = 365


def load_closes():
    frames = []
    for a in ASSETS:
        df = fetch_history(a, "1d", DAYS)[["timestamp", "close"]].rename(columns={"close": a})
        frames.append(df.set_index("timestamp"))
    closes = pd.concat(frames, axis=1, join="inner").dropna()
    return closes


def stats(net):
    eq = (1 + net).cumprod()
    sd = net.std()
    return {"sharpe": net.mean() / sd * np.sqrt(BPY) if sd else 0,
            "ret": eq.iloc[-1] - 1,
            "maxdd": (eq / eq.cummax() - 1).min()}


def main():
    closes = load_closes()
    rets = closes.pct_change().fillna(0)
    print(f"{len(closes)} días comunes ({closes.index[0].date()} → {closes.index[-1].date()})\n")

    # Señales por activo
    sig = pd.DataFrame({a: sma_signal(closes[a], FAST, SLOW).astype(int) for a in ASSETS},
                       index=closes.index)
    n_long = sig.sum(axis=1)
    weights = sig.div(n_long.replace(0, np.nan), axis=0).fillna(0)  # equal-weight entre long

    pos = weights.shift(1).fillna(0)
    gross = (pos * rets).sum(axis=1)
    turnover = (weights - weights.shift(1)).abs().sum(axis=1).fillna(0)
    net = gross - turnover * COST_PER_SIDE
    port = stats(net)

    # Benchmarks
    bh_btc = stats(rets["BTC/USDT"])
    bh_eq = stats(rets.mean(axis=1))                       # hold equiponderado de los 4
    # Estrategia en un solo activo (BTC) para comparar
    s_btc = sma_signal(closes["BTC/USDT"], FAST, SLOW).astype(int)
    btc_net = s_btc.shift(1).fillna(0) * rets["BTC/USDT"] - s_btc.diff().abs().fillna(0) * COST_PER_SIDE
    strat_btc = stats(btc_net)

    def row(name, m):
        print(f"{name:<34}{m['sharpe']:>8.2f}{m['ret']*100:>10.0f}%{m['maxdd']*100:>9.0f}%")

    print("=" * 62)
    print("EXP I — Portfolio trend-following (4 activos) vs benchmarks")
    print("=" * 62)
    print(f"{'estrategia':<34}{'Sharpe':>8}{'ret':>11}{'maxDD':>9}")
    print("-" * 62)
    row("PORTFOLIO trend (4 activos)", port)
    row("Estrategia 1 activo (BTC)", strat_btc)
    row("B&H BTC", bh_btc)
    row("B&H equiponderado (4)", bh_eq)
    print("=" * 62)
    exp = (port["sharpe"] >= strat_btc["sharpe"]) and (port["maxdd"] > strat_btc["maxdd"])
    if exp:
        print(f"-> El portfolio MEJORA al single-asset (Sharpe {port['sharpe']:.2f}, "
              f"maxDD {port['maxdd']*100:.0f}% vs {strat_btc['maxdd']*100:.0f}%). "
              f"Diversificar funciona.")
    else:
        print(f"-> Portfolio Sharpe {port['sharpe']:.2f} maxDD {port['maxdd']*100:.0f}%: "
              f"no mejora claramente al single-asset.")


if __name__ == "__main__":
    main()
