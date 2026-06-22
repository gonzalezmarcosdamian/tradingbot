"""
Exp E — ML + order-flow (microestructura).

Usa features de FLUJO DE ÓRDENES que el precio puro no tiene (taker buy ratio =
fracción del volumen que fue compra agresiva, nº de trades, volumen), más
técnicos clásicos, y entrena un modelo WALK-FORWARD para predecir la dirección
de la próxima vela. Backtest con costos.

Anti look-ahead: features en t, target = retorno t->t+1, modelo entrenado solo
con el pasado de cada ventana.

Uso: python run_research_ml.py
"""

import sys
import time
import numpy as np
import pandas as pd

from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier

from signals_research import rsi
from backtest import COST_PER_SIDE, BARS_PER_YEAR

DAYS = 730
TRAIN = 24 * 180
TEST = 24 * 30


def fetch_klines_raw(symbol="BTCUSDT", interval="1h", days=DAYS):
    """Klines crudos de Binance (12 campos, incluye taker buy volume)."""
    import ccxt
    ex = ccxt.binance({"enableRateLimit": True})
    step = ex.parse_timeframe(interval) * 1000
    start = ex.milliseconds() - days * 86400 * 1000
    rows = []
    while True:
        batch = ex.publicGetKlines({"symbol": symbol, "interval": interval,
                                    "limit": 1000, "startTime": start})
        if not batch:
            break
        rows += batch
        start = int(batch[-1][0]) + step
        if len(batch) < 1000:
            break
        time.sleep(ex.rateLimit / 1000)
    df = pd.DataFrame({
        "close": [float(r[4]) for r in rows],
        "volume": [float(r[5]) for r in rows],
        "trades": [float(r[8]) for r in rows],
        "taker_buy": [float(r[9]) for r in rows],
    })
    return df.drop_duplicates().reset_index(drop=True)


def features(df):
    c = df["close"]
    f = pd.DataFrame(index=df.index)
    f["ret1"] = c.pct_change()
    f["ret4"] = c.pct_change(4)
    f["ret24"] = c.pct_change(24)
    f["rsi"] = rsi(c, 14)
    f["vol"] = f["ret1"].rolling(24).std()
    f["ma_dist"] = c / c.rolling(48).mean() - 1
    f["taker_ratio"] = (df["taker_buy"] / df["volume"]).clip(0, 1)        # order flow
    f["taker_ratio_ma"] = f["taker_ratio"].rolling(24).mean()
    f["trades_z"] = (df["trades"] - df["trades"].rolling(48).mean()) / df["trades"].rolling(48).std()
    f["vol_z"] = (df["volume"] - df["volume"].rolling(48).mean()) / df["volume"].rolling(48).std()
    return f


def backtest(signal, close):
    pos = signal.shift(1).fillna(0)
    ret = close.pct_change().fillna(0)
    net = pos * ret - pos.diff().abs().fillna(0) * COST_PER_SIDE
    eq = (1 + net).cumprod()
    sd = net.std()
    return {"ret": eq.iloc[-1] - 1,
            "sharpe": net.mean() / sd * np.sqrt(BARS_PER_YEAR) if sd else 0,
            "maxdd": (eq / eq.cummax() - 1).min(),
            "exposure": (pos > 0).mean()}


def walk_forward_ml(X, y, close, make_model):
    n = len(X)
    sig = np.zeros(n)
    start = 0
    while start + TRAIN + TEST <= n:
        model = make_model()
        model.fit(X[start:start + TRAIN], y[start:start + TRAIN])
        proba = model.predict_proba(X[start + TRAIN:start + TRAIN + TEST])[:, 1]
        sig[start + TRAIN:start + TRAIN + TEST] = (proba > 0.5).astype(int)
        start += TEST
    return backtest(pd.Series(sig, index=close.index), close)


def pct(x):
    return f"{x*100:+.1f}%"


def main():
    print("Bajando klines crudos (con order-flow) de Binance...", flush=True)
    try:
        df = fetch_klines_raw()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(1)

    feat_cols = ["ret1", "ret4", "ret24", "rsi", "vol", "ma_dist",
                 "taker_ratio", "taker_ratio_ma", "trades_z", "vol_z"]
    f = features(df)
    f["y"] = (df["close"].shift(-1) > df["close"]).astype(int)
    data = pd.concat([f, df["close"]], axis=1).dropna().reset_index(drop=True)
    X = data[feat_cols].to_numpy()
    y = data["y"].to_numpy()
    close = data["close"]

    bh = backtest(pd.Series(1, index=close.index), close)
    print(f"\n{'='*64}")
    print(f"EXP E — ML + order-flow — BTC/USDT 1h, {len(data)} muestras")
    print(f"Buy & Hold: ret {pct(bh['ret'])}  Sharpe {bh['sharpe']:.2f}  maxDD {pct(bh['maxdd'])}")
    print("=" * 64)
    print(f"{'modelo':<28}{'ret':>9}{'Sharpe':>8}{'maxDD':>9}{'expos.':>8}")
    print("-" * 64)

    # Baseline order-flow sin ML: long cuando hay más compra agresiva
    of = (pd.Series(X[:, feat_cols.index("taker_ratio")], index=close.index) > 0.5).astype(int)
    m_of = backtest(of, close)
    print(f"{'Order-flow (taker>0.5)':<28}{pct(m_of['ret']):>9}{m_of['sharpe']:>8.2f}{pct(m_of['maxdd']):>9}{pct(m_of['exposure']):>8}")

    m_lr = walk_forward_ml(X, y, close, lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)))
    print(f"{'LogisticRegression (WF)':<28}{pct(m_lr['ret']):>9}{m_lr['sharpe']:>8.2f}{pct(m_lr['maxdd']):>9}{pct(m_lr['exposure']):>8}")

    m_gb = walk_forward_ml(X, y, close, lambda: GradientBoostingClassifier(n_estimators=80, max_depth=3))
    print(f"{'GradientBoosting (WF)':<28}{pct(m_gb['ret']):>9}{m_gb['sharpe']:>8.2f}{pct(m_gb['maxdd']):>9}{pct(m_gb['exposure']):>8}")

    print("=" * 64)
    best = max([("order-flow", m_of), ("logistic", m_lr), ("gboost", m_gb)], key=lambda x: x[1]["sharpe"])
    if best[1]["sharpe"] > bh["sharpe"] and best[1]["maxdd"] > bh["maxdd"]:
        print(f"-> '{best[0]}' Sharpe {best[1]['sharpe']:.2f} SUPERA al B&H. ¡Vale profundizar!")
    else:
        print(f"-> Mejor '{best[0]}' Sharpe {best[1]['sharpe']:.2f}: NO supera al B&H.")


if __name__ == "__main__":
    main()
