"""
Exp C — Market-neutral: par BTC/ETH (reversión de spread).

Idea: en vez de adivinar la dirección (que viene fallando), apostar a que el
RATIO BTC/ETH revierte a su media. Long el spread (long BTC, short ETH) cuando
el ratio está barato (z-score bajo), short el spread cuando está caro. Saca el
riesgo direccional del mercado.

OJO: requiere SHORT (perps/margin), que el bot spot long-only no hace. Este
backtest mide si el EDGE existe; implementarlo sería otra etapa.

Uso: python run_research_pairs.py
"""

import numpy as np
import pandas as pd

from run_backtest import fetch_history
from backtest import COST_PER_SIDE, BARS_PER_YEAR

DAYS = 730


def load_pair():
    btc = fetch_history("BTC/USDT", "1h", DAYS)[["timestamp", "close"]].rename(columns={"close": "btc"})
    eth = fetch_history("ETH/USDT", "1h", DAYS)[["timestamp", "close"]].rename(columns={"close": "eth"})
    df = pd.merge(btc, eth, on="timestamp", how="inner").reset_index(drop=True)
    return df


def spread_positions(z, entry, exit_):
    """Máquina de 3 estados: +1 long spread, -1 short spread, 0 flat."""
    pos = np.zeros(len(z))
    state = 0
    zv = z.to_numpy()
    for i in range(len(zv)):
        if np.isnan(zv[i]):
            state = 0
        elif state == 0:
            if zv[i] < -entry:
                state = 1
            elif zv[i] > entry:
                state = -1
        elif state == 1 and zv[i] > -exit_:
            state = 0
        elif state == -1 and zv[i] < exit_:
            state = 0
        pos[i] = state
    return pd.Series(pos, index=z.index)


def backtest_pair(df, window, entry, exit_):
    ratio = df["btc"] / df["eth"]
    z = (ratio - ratio.rolling(window, min_periods=window).mean()) / ratio.rolling(window, min_periods=window).std()
    pos = spread_positions(z, entry, exit_)
    btc_ret = df["btc"].pct_change().fillna(0)
    eth_ret = df["eth"].pct_change().fillna(0)
    spread_ret = pos.shift(1).fillna(0) * (btc_ret - eth_ret)
    # Cada cambio de posición opera AMBAS piernas → doble costo
    cost = pos.diff().abs().fillna(0) * 2 * COST_PER_SIDE
    net = spread_ret - cost
    equity = (1 + net).cumprod()
    sd = net.std()
    sharpe = net.mean() / sd * np.sqrt(BARS_PER_YEAR) if sd else 0
    maxdd = (equity / equity.cummax() - 1).min()
    n_trades = int((pos.diff().abs() > 0).sum())
    return {"ret": equity.iloc[-1] - 1, "sharpe": sharpe, "maxdd": maxdd, "trades": n_trades}


def pct(x):
    return f"{x*100:+.1f}%"


def main():
    df = load_pair()
    print("\n" + "=" * 60)
    print(f"EXP C — Market-neutral BTC/ETH (reversión de spread), 2 años")
    print(f"{len(df)} velas alineadas")
    print("=" * 60)
    print(f"{'params (W,entry,exit)':<24}{'ret':>10}{'Sharpe':>8}{'maxDD':>9}{'trades':>8}")
    print("-" * 60)
    best = (None, -9, None)
    for w in (48, 120, 240):
        for entry in (1.5, 2.0, 2.5):
            r = backtest_pair(df, w, entry, 0.5)
            name = f"W={w} e={entry} x=0.5"
            print(f"{name:<24}{pct(r['ret']):>10}{r['sharpe']:>8.2f}{pct(r['maxdd']):>9}{r['trades']:>8}")
            if r["sharpe"] > best[1]:
                best = (name, r["sharpe"], r)
    print("=" * 60)
    if best[1] > 0.5:
        print(f"-> '{best[0]}' Sharpe {best[1]:.2f}: HAY señal market-neutral. Vale profundizar.")
    else:
        print(f"-> Mejor '{best[0]}' Sharpe {best[1]:.2f}: sin edge claro (neto de costos).")


if __name__ == "__main__":
    main()
