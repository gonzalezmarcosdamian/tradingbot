"""
run_strategy_comparison.py — Compara la estrategia base vs. mejoras con filtros.

Para cada variante corre walk-forward y reporta el número honesto (OOS),
comparado contra buy-and-hold. Objetivo: ver qué filtro (o combinación)
mejora el edge, reduce drawdown y estabiliza parámetros.

Uso:
  python run_strategy_comparison.py

Baja data real de Binance (en tu máquina). Si no hay acceso a Binance, define
SOURCE_CSV con un CSV de velas para correr offline.
"""

import os
import sys
import numpy as np
import pandas as pd

from strategy import STRATEGIES
from backtest import run_backtest, COST_PER_SIDE, BARS_PER_YEAR
from strategy_filters import trend_filter, regime_filter, apply_trailing_stop

SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"
DAYS = 730
FAST_RANGE = range(10, 51, 5)
SLOW_RANGE = range(50, 201, 10)
TRAIN_BARS = 24 * 180
TEST_BARS = 24 * 60
SOURCE_CSV = os.getenv("SOURCE_CSV", "")  # opcional: correr desde CSV


def load_data():
    if SOURCE_CSV:
        df = pd.read_csv(SOURCE_CSV)
        return df[["close"]].reset_index(drop=True)
    import ccxt, time
    ex = ccxt.binance({"enableRateLimit": True})
    ex.load_markets()
    ms = ex.parse_timeframe(TIMEFRAME) * 1000
    since = ex.milliseconds() - DAYS * 86400 * 1000
    rows = []
    while True:
        batch = ex.fetch_ohlcv(SYMBOL, TIMEFRAME, since=since, limit=1000)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + ms
        if len(batch) < 1000:
            break
        time.sleep(ex.rateLimit / 1000)
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "close", "v"])
    return df[["close"]].reset_index(drop=True)


def build_signal(df, strat_name, fast, slow, variant):
    """Genera la señal base y aplica los filtros de la variante."""
    sig = STRATEGIES[strat_name](df["close"], fast, slow)
    if "trend" in variant:
        sig = trend_filter(sig, df, trend_ma=200)
    if "regime" in variant:
        sig = regime_filter(sig, df, window=48, min_strength=0.04)
    if "trailing" in variant:
        sig = apply_trailing_stop(sig, df, trail_pct=0.05)
    return sig


def wf_for_variant(df, strat_name, variant):
    """Walk-forward para una variante (optimiza fast/slow en train, mide en test)."""
    df = df.reset_index(drop=True)
    n = len(df)
    oos = []
    fasts, slows = [], []
    start = 0
    while start + TRAIN_BARS + TEST_BARS <= n:
        train = df.iloc[start:start + TRAIN_BARS]
        # Optimizar fast/slow en train para esta variante
        best, best_sharpe = None, -np.inf
        for f in FAST_RANGE:
            for s in SLOW_RANGE:
                if f >= s:
                    continue
                sig = build_signal(train, strat_name, f, s, variant)
                pos = sig.shift(1).fillna(0)
                ret = df["close"].iloc[start:start+TRAIN_BARS].pct_change().fillna(0).values
                sr = pos.values * ret
                tr = np.abs(np.diff(np.concatenate([[0], pos.values]))) * COST_PER_SIDE
                net = sr - tr
                sd = net.std()
                sharpe = net.mean()/sd*np.sqrt(BARS_PER_YEAR) if sd > 0 else -np.inf
                if sharpe > best_sharpe:
                    best_sharpe, best = sharpe, (f, s)
        bf, bs = best
        fasts.append(bf); slows.append(bs)
        # Medir en test con esos params (calcular señal sobre train+test, tomar test)
        combined = df.iloc[start:start + TRAIN_BARS + TEST_BARS]
        sig_full = build_signal(combined, strat_name, bf, bs, variant)
        sig_test = sig_full.iloc[TRAIN_BARS:].reset_index(drop=True)
        close_test = df["close"].iloc[start+TRAIN_BARS:start+TRAIN_BARS+TEST_BARS].reset_index(drop=True)
        pos = sig_test.shift(1).fillna(0)
        ret = close_test.pct_change().fillna(0)
        net = pos*ret - pos.diff().abs().fillna(0)*COST_PER_SIDE
        oos.append(net)
        start += TEST_BARS
    if not oos:
        return None
    oos = pd.concat(oos, ignore_index=True)
    equity = (1+oos).cumprod()
    years = len(oos)/BARS_PER_YEAR
    sd = oos.std()
    return {
        "ret": equity.iloc[-1]-1,
        "ann": equity.iloc[-1]**(1/years)-1 if years > 0 else 0,
        "sharpe": oos.mean()/sd*np.sqrt(BARS_PER_YEAR) if sd > 0 else 0,
        "maxdd": (equity/equity.cummax()-1).min(),
        "fast_std": np.std(fasts),
        "slow_std": np.std(slows),
    }


VARIANTS = [
    ("base", []),
    ("+trend", ["trend"]),
    ("+regime", ["regime"]),
    ("+trailing", ["trailing"]),
    ("+trend+regime", ["trend", "regime"]),
    ("+trend+regime+trailing", ["trend", "regime", "trailing"]),
]


def main():
    print("Cargando data...")
    df = load_data()
    bh = df["close"].iloc[-1]/df["close"].iloc[0]-1
    print(f"{len(df)} velas | Buy & Hold: {bh*100:+.1f}%\n")

    for strat in STRATEGIES:
        print(f"\n{'='*72}\n{strat}\n{'='*72}")
        print(f"{'variante':<28}{'ret OOS':>10}{'anual':>9}{'Sharpe':>8}{'maxDD':>9}{'estab.':>9}")
        print("-"*72)
        for name, filters in VARIANTS:
            r = wf_for_variant(df, strat, filters)
            if r is None:
                continue
            estab = "ok" if (r["fast_std"] <= 12 and r["slow_std"] <= 40) else "INESTABLE"
            print(f"{name:<28}{r['ret']*100:>9.1f}%{r['ann']*100:>8.1f}%"
                  f"{r['sharpe']:>8.2f}{r['maxdd']*100:>8.1f}%{estab:>9}")

    print(f"\n{'='*72}")
    print("Buscamos: mayor Sharpe, menor maxDD (menos negativo), 'ok' en estabilidad.")
    print("Si nada supera al B&H en Sharpe Y mejora el drawdown, el cruce no es viable.")
    print("="*72)


if __name__ == "__main__":
    main()
