"""
run_research.py — Busca edge en familias de estrategias distintas al cruce.

Corre walk-forward out-of-sample (data real de Binance, sin claves) para:
  RSI reversion, Bollinger reversion, Donchian breakout (+ filtro de tendencia)
  y Momentum. Compara el número honesto (OOS) contra buy-and-hold.

Uso:
  python run_research.py

Si no hay acceso a Binance, definí SOURCE_CSV con un CSV de velas OHLC.
"""

import itertools
import os
import sys

import numpy as np

from research_wf import generic_walk_forward, oos_metrics
from signals_research import (
    rsi_reversion_signal,
    bollinger_reversion_signal,
    donchian_breakout_signal,
    momentum_signal,
)
from strategy_filters import trend_filter

SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"
DAYS = 730
TRAIN_BARS = 24 * 180
TEST_BARS = 24 * 60
SOURCE_CSV = os.getenv("SOURCE_CSV", "")


def grid(**kw):
    """Producto cartesiano de parámetros → lista de dicts."""
    keys = list(kw)
    return [dict(zip(keys, vals)) for vals in itertools.product(*kw.values())]


# (builder, grilla de params) por estrategia
STRATEGIES_RESEARCH = {
    "RSI reversion": (
        lambda df, p: rsi_reversion_signal(df["close"], p["period"], p["oversold"], p["exit_level"]),
        grid(period=[9, 14], oversold=[20, 25, 30], exit_level=[50, 55, 60]),
    ),
    "Bollinger reversion": (
        lambda df, p: bollinger_reversion_signal(df["close"], p["window"], p["k"]),
        grid(window=[20, 30, 50], k=[1.5, 2.0, 2.5]),
    ),
    "Donchian breakout": (
        lambda df, p: donchian_breakout_signal(df, p["entry_n"], p["exit_n"]),
        grid(entry_n=[20, 30, 55], exit_n=[10, 15, 20]),
    ),
    "Donchian + trend200": (
        lambda df, p: trend_filter(donchian_breakout_signal(df, p["entry_n"], p["exit_n"]), df, 200),
        grid(entry_n=[20, 30, 55], exit_n=[10, 15, 20]),
    ),
    "Momentum (TS)": (
        lambda df, p: momentum_signal(df["close"], p["lookback"]),
        grid(lookback=[72, 168, 336]),
    ),
}


def load_data():
    if SOURCE_CSV:
        import pandas as pd
        df = pd.read_csv(SOURCE_CSV)
        cols = {c.lower(): c for c in df.columns}
        return df.rename(columns={cols.get("close", "close"): "close"}).reset_index(drop=True)
    from run_backtest import fetch_history
    return fetch_history(SYMBOL, TIMEFRAME, DAYS)


def main():
    print("Cargando data real de Binance (puede tardar)...", flush=True)
    try:
        df = load_data()
    except Exception as e:
        print(f"Error bajando data: {e}", file=sys.stderr)
        sys.exit(1)

    if len(df) < TRAIN_BARS + TEST_BARS:
        print("No hay suficiente data para el walk-forward.", file=sys.stderr)
        sys.exit(1)

    bh = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    bh_ret = df["close"].pct_change().fillna(0)
    bh_sharpe = bh_ret.mean() / bh_ret.std() * np.sqrt(24 * 365) if bh_ret.std() > 0 else 0
    bh_equity = (1 + bh_ret).cumprod()
    bh_dd = (bh_equity / bh_equity.cummax() - 1).min()

    print(f"\n{len(df)} velas | BENCHMARK Buy & Hold: ret {bh*100:+.1f}%  "
          f"Sharpe {bh_sharpe:.2f}  maxDD {bh_dd*100:.1f}%\n")
    print(f"{'estrategia':<22}{'ret OOS':>9}{'anual':>8}{'Sharpe':>8}"
          f"{'maxDD':>8}{'expos.':>8}{'estab.':>8}")
    print("-" * 70)

    results = {}
    for name, (builder, param_grid) in STRATEGIES_RESEARCH.items():
        wf = generic_walk_forward(df, builder, param_grid, TRAIN_BARS, TEST_BARS)
        m = oos_metrics(wf["oos_returns"])
        if not m:
            continue
        results[name] = m
        # Estabilidad: nº de combinaciones distintas elegidas entre ventanas
        n_distinct = len({tuple(sorted(p.items())) for p in wf["chosen"]})
        estab = "ok" if n_distinct <= 2 else f"{n_distinct} sets"
        print(f"{name:<22}{m['ret']*100:>8.1f}%{m['ann']*100:>7.1f}%"
              f"{m['sharpe']:>8.2f}{m['maxdd']*100:>7.1f}%{m['exposure']*100:>7.1f}%{estab:>8}")

    print("-" * 70)
    # Veredicto automático
    beat = [n for n, m in results.items()
            if m["sharpe"] > bh_sharpe and m["maxdd"] > bh_dd]
    print(f"\nBar a superar: Sharpe > {bh_sharpe:.2f} (B&H) Y maxDD mejor que {bh_dd*100:.1f}%.")
    if beat:
        print(f"✅ Candidata(s) con edge OOS: {', '.join(beat)}")
        print("   Siguiente paso: validar robustez (otros períodos, otro par) antes de paper.")
    else:
        print("❌ Ninguna estrategia le gana al Buy & Hold en Sharpe Y drawdown OOS.")
        print("   BTC en este período fue difícil para long-only sistemático.")


if __name__ == "__main__":
    main()
