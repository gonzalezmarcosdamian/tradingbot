"""
run_backtest.py — Etapa 2: research de estrategias.

Qué hace:
  1. Baja ~2 años de velas 1h de BTC/USDT (data pública, sin claves).
  2. Corre un backtest in-sample naive (con mejores params) — solo de referencia.
  3. Corre walk-forward (out-of-sample) para SMA y EMA.
  4. Compara todo contra buy-and-hold y marca señales de overfitting.

Uso:
  python run_backtest.py
"""

import sys
import time
import ccxt
import numpy as np
import pandas as pd

from strategy import STRATEGIES
from backtest import run_backtest
from walkforward import walk_forward, summarize_oos, optimize_params

SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"
DAYS = 730  # ~2 años

# Rangos de parámetros a optimizar
FAST_RANGE = range(10, 51, 5)    # 10,15,...,50
SLOW_RANGE = range(50, 201, 10)  # 50,60,...,200

# Walk-forward: ventanas en nº de velas 1h
TRAIN_BARS = 24 * 180  # 180 días de entrenamiento
TEST_BARS = 24 * 60    # 60 días de test


def fetch_history(symbol, timeframe, days):
    """Baja velas históricas paginando (data pública, sin API key)."""
    exchange = ccxt.binance({"enableRateLimit": True})
    exchange.load_markets()

    ms_per_bar = exchange.parse_timeframe(timeframe) * 1000
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
    all_rows = []

    print(f"📥 Bajando ~{days} días de {symbol} {timeframe}...")
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        all_rows += batch
        since = batch[-1][0] + ms_per_bar
        if len(batch) < 1000:
            break
        time.sleep(exchange.rateLimit / 1000)

    df = pd.DataFrame(
        all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"]
    ).drop_duplicates(subset="timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    print(f"   {len(df)} velas bajadas ({df['timestamp'].iloc[0].date()} → {df['timestamp'].iloc[-1].date()})\n")
    return df.reset_index(drop=True)


def pct(x):
    return f"{x*100:,.2f}%"


def main():
    try:
        df = fetch_history(SYMBOL, TIMEFRAME, DAYS)
    except Exception as e:
        print(f"❌ Error bajando data: {e}")
        sys.exit(1)

    if len(df) < TRAIN_BARS + TEST_BARS:
        print("❌ No hay suficiente data para el walk-forward.")
        sys.exit(1)

    # Benchmark buy & hold
    bh = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    print("=" * 64)
    print(f"BENCHMARK Buy & Hold: {pct(bh)}")
    print("=" * 64)

    for strat_name in STRATEGIES:
        print(f"\n{'#'*64}\n# Estrategia: {strat_name}\n{'#'*64}")

        # --- 1. In-sample naive (solo referencia, propenso a overfitting) ---
        (bf, bs), _ = optimize_params(df, strat_name, FAST_RANGE, SLOW_RANGE)
        signal = STRATEGIES[strat_name](df["close"], bf, bs)
        ins = run_backtest(df, signal)
        print(f"\n[IN-SAMPLE naive] mejores params: fast={bf}, slow={bs}")
        print(f"  Retorno total : {pct(ins['total_return'])}  (B&H {pct(ins['bh_return'])})")
        print(f"  Sharpe        : {ins['sharpe']:.2f}  (B&H {ins['bh_sharpe']:.2f})")
        print(f"  Max drawdown  : {pct(ins['max_drawdown'])}  (B&H {pct(ins['bh_max_drawdown'])})")
        print(f"  Trades        : {ins['n_trades']}  | Exposición: {pct(ins['exposure'])}  | Win rate: {pct(ins['win_rate'])}")
        print("  ⚠️  In-sample = optimista. El número honesto es el de abajo.")

        # --- 2. Walk-forward (out-of-sample, el número real) ---
        wf = walk_forward(df, strat_name, FAST_RANGE, SLOW_RANGE, TRAIN_BARS, TEST_BARS)
        oos = summarize_oos(wf["oos_returns"])
        print(f"\n[WALK-FORWARD out-of-sample] {len(wf['windows'])} ventanas")
        if oos:
            print(f"  Retorno total OOS : {pct(oos['oos_total_return'])}")
            print(f"  Retorno anualiz.  : {pct(oos['oos_ann_return'])}")
            print(f"  Sharpe OOS        : {oos['oos_sharpe']:.2f}")
            print(f"  Max drawdown OOS  : {pct(oos['oos_max_drawdown'])}")

            # Señal de inestabilidad: ¿saltan mucho los params óptimos?
            fasts = [w["fast"] for w in wf["windows"]]
            slows = [w["slow"] for w in wf["windows"]]
            print(f"  Params por ventana: fast {min(fasts)}-{max(fasts)}, slow {min(slows)}-{max(slows)}")
            if np.std(fasts) > 12 or np.std(slows) > 40:
                print("  ⚠️  Los params óptimos saltan mucho entre ventanas → estrategia inestable.")

    print("\n" + "=" * 64)
    print("Lectura: si el Sharpe OOS no le gana al B&H, la estrategia no aporta edge.")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    main()
