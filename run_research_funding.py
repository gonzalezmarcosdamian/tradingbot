"""
Exp D — Señales no-precio: funding rate de perpetuos BTC/USDT.

Idea: el funding rate (lo que pagan longs/shorts cada 8h) mide el
posicionamiento del mercado, info que el precio puro no tiene. Dos hipótesis:
  - CONTRARIAN: funding muy negativo = capitulación de shorts/miedo extremo →
    suele marcar pisos → comprar.
  - CARRY/TREND: funding positivo = sentimiento alcista sostenido → comprar.

Backtest sobre barras de 8h (alineadas al funding), neto de costos.

Uso: python run_research_funding.py
"""

import sys
import time
import numpy as np
import pandas as pd

from backtest import COST_PER_SIDE

SYMBOL = "BTC/USDT:USDT"   # perpetuo USDT-margined
BARS_PER_YEAR_8H = 365 * 3
DAYS = 700


def fetch_8h_and_funding():
    import ccxt
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    ex.load_markets()
    since0 = ex.milliseconds() - DAYS * 86400 * 1000

    # OHLCV 8h
    ms = ex.parse_timeframe("8h") * 1000
    since = since0
    rows = []
    while True:
        batch = ex.fetch_ohlcv(SYMBOL, "8h", since=since, limit=1000)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + ms
        if len(batch) < 1000:
            break
        time.sleep(ex.rateLimit / 1000)
    price = pd.DataFrame(rows, columns=["timestamp", "o", "h", "l", "close", "v"])[["timestamp", "close"]]

    # Funding rate history
    since = since0
    frows = []
    while True:
        batch = ex.fetch_funding_rate_history(SYMBOL, since=since, limit=1000)
        if not batch:
            break
        frows += [{"timestamp": b["timestamp"], "funding": b["fundingRate"]} for b in batch]
        since = batch[-1]["timestamp"] + 1
        if len(batch) < 1000:
            break
        time.sleep(ex.rateLimit / 1000)
    funding = pd.DataFrame(frows).drop_duplicates(subset="timestamp")

    df = pd.merge_asof(price.sort_values("timestamp"), funding.sort_values("timestamp"),
                       on="timestamp", direction="backward").dropna().reset_index(drop=True)
    return df


def bt(df, signal):
    pos = signal.shift(1).fillna(0)
    ret = df["close"].pct_change().fillna(0)
    net = pos * ret - pos.diff().abs().fillna(0) * COST_PER_SIDE
    eq = (1 + net).cumprod()
    sd = net.std()
    return {
        "ret": eq.iloc[-1] - 1,
        "sharpe": net.mean() / sd * np.sqrt(BARS_PER_YEAR_8H) if sd else 0,
        "maxdd": (eq / eq.cummax() - 1).min(),
        "exposure": (pos > 0).mean(),
    }


def hold_between(entries, exits, index):
    s = pd.Series(np.nan, index=index)
    s[entries] = 1.0
    s[exits] = 0.0
    return s.ffill().fillna(0).astype(int)


def pct(x):
    return f"{x*100:+.1f}%"


def main():
    print("Bajando 8h OHLCV + funding de Binance perp...", flush=True)
    try:
        df = fetch_8h_and_funding()
    except Exception as e:
        print(f"No se pudo bajar funding: {e}", file=sys.stderr)
        sys.exit(1)
    f = df["funding"]
    z = (f - f.rolling(90, min_periods=90).mean()) / f.rolling(90, min_periods=90).std()

    bh = bt(df, pd.Series(1, index=df.index))
    print("\n" + "=" * 64)
    print(f"EXP D — Funding rate (no-precio) — {SYMBOL}, {len(df)} barras 8h")
    print(f"Buy & Hold: ret {pct(bh['ret'])}  Sharpe {bh['sharpe']:.2f}  maxDD {pct(bh['maxdd'])}")
    print("=" * 64)
    print(f"{'señal':<32}{'ret':>9}{'Sharpe':>8}{'maxDD':>9}{'expos.':>8}")
    print("-" * 64)
    variants = {
        "Carry: funding > 0": (f > 0).astype(int),
        "Carry: funding > media90": (z > 0).astype(int),
        "Contrarian: z < -1 (long)": hold_between(z < -1, z > 0, df.index),
        "Contrarian: z < -2 (long)": hold_between(z < -2, z > 0, df.index),
        "Contrarian: funding < 0": (f < 0).astype(int),
    }
    best = (None, -9, None)
    for name, sig in variants.items():
        m = bt(df, sig)
        print(f"{name:<32}{pct(m['ret']):>9}{m['sharpe']:>8.2f}{pct(m['maxdd']):>9}{pct(m['exposure']):>8}")
        if m["sharpe"] > best[1]:
            best = (name, m["sharpe"], m)
    print("=" * 64)
    bm = best[2]
    if best[1] > bh["sharpe"] and bm["maxdd"] > bh["maxdd"]:
        print(f"-> '{best[0]}' Sharpe {best[1]:.2f} SUPERA al B&H. ¡Vale profundizar!")
    else:
        print(f"-> Mejor '{best[0]}' Sharpe {best[1]:.2f}: NO supera al B&H.")


if __name__ == "__main__":
    main()
