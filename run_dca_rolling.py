"""
run_dca_rolling.py — Rolling de ventanas de 12 meses: Smart DCA vs DCA plano.

En vez de un solo año, desliza ventanas de 365 días a lo largo de toda la
historia disponible y, en cada una, simula ambos DCA (misma lógica que en vivo,
sin look-ahead). Responde: ¿el Smart DCA le gana al plano de forma consistente,
o depende del período?

Uso:
  python run_dca_rolling.py
"""

import sys
import time
import ccxt

from dca import DCAConfig, DCAState, analyze, decide, maybe_reset_period

SYMBOL = "BTC/USDT"
TIMEFRAME = "1d"
HISTORY_DAYS = 1500        # ~4 años para tener varias ventanas
WINDOW_DAYS = 365          # cada ventana = 12 meses
SLIDE_DAYS = 30            # corre la ventana de a 1 mes
STEP_DAYS = 7              # compra semanal
WARMUP = 35
DAY = 86400
PERIOD_BUDGET = 100.0
BUYS_PER_PERIOD = 4


def fetch_daily(symbol, days):
    ex = ccxt.binance({"enableRateLimit": True})
    ex.load_markets()
    ms = ex.parse_timeframe(TIMEFRAME) * 1000
    since = ex.milliseconds() - days * DAY * 1000
    rows = []
    while True:
        batch = ex.fetch_ohlcv(symbol, TIMEFRAME, since=since, limit=1000)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + ms
        if len(batch) < 1000:
            break
        time.sleep(ex.rateLimit / 1000)
    # dedup por timestamp
    seen, out = set(), []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0]); out.append(r)
    return out


def config():
    return DCAConfig(
        symbol=SYMBOL, period_budget=PERIOD_BUDGET, buys_per_period=BUYS_PER_PERIOD,
        period_seconds=STEP_DAYS * BUYS_PER_PERIOD * DAY,
        timeframe="1d", ma_period=30, rsi_period=14,
        sensitivity=5.0, rsi_sensitivity=1.0, min_mult=0.3, max_mult=2.5, smart=True,
    )


def simulate(closes, ts, start, end, cfg):
    """Simula smart vs plano comprando semanalmente en [start, end]."""
    flat_quote = PERIOD_BUDGET / BUYS_PER_PERIOD
    state = DCAState()
    s_btc = s_spent = f_btc = f_spent = 0.0
    for i in range(start, end, STEP_DAYS):
        now, price = ts[i], closes[i]
        state = maybe_reset_period(state, cfg, now)
        a = analyze(closes[: i + 1], price, cfg)
        d = decide(cfg, state, now, available_cash=1e12, multiplier=a.multiplier)
        if not d.should_buy:
            continue
        state.spent_this_period += d.quote_amount
        state.buys_this_period += 1
        state.last_buy_ts = now
        s_btc += d.quote_amount / price
        s_spent += d.quote_amount
        f_btc += flat_quote / price
        f_spent += flat_quote
    final = closes[min(end, len(closes) - 1)]
    return {
        "smart_val": s_btc * final, "flat_val": f_btc * final,
        "smart_spent": s_spent, "flat_spent": f_spent,
        "smart_btc": s_btc, "flat_btc": f_btc,
    }


def main():
    print("Bajando historia diaria de Binance...", flush=True)
    try:
        rows = fetch_daily(SYMBOL, HISTORY_DAYS)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(1)
    closes = [r[4] for r in rows]
    ts = [r[0] // 1000 for r in rows]
    n = len(closes)
    print(f"{n} días de historia.\n")

    cfg = config()
    edges_val, edges_cost = [], []
    wins = 0
    first = max(WARMUP, 0)
    starts = range(first, n - WINDOW_DAYS, SLIDE_DAYS)
    for s in starts:
        r = simulate(closes, ts, s, s + WINDOW_DAYS, cfg)
        if r["smart_btc"] <= 0 or r["flat_val"] <= 0:
            continue
        edge_val = (r["smart_val"] - r["flat_val"]) / r["flat_val"] * 100
        s_avg = r["smart_spent"] / r["smart_btc"]
        f_avg = r["flat_spent"] / r["flat_btc"]
        edge_cost = (f_avg - s_avg) / f_avg * 100
        edges_val.append(edge_val); edges_cost.append(edge_cost)
        if edge_val > 0:
            wins += 1

    if not edges_val:
        print("No hubo ventanas suficientes."); return
    k = len(edges_val)
    avg_val = sum(edges_val) / k
    avg_cost = sum(edges_cost) / k
    med_val = sorted(edges_val)[k // 2]
    print("=" * 60)
    print(f"ROLLING 12 meses — {k} ventanas (cada {SLIDE_DAYS}d), Smart DCA vs plano")
    print("=" * 60)
    print(f"Ventanas donde Smart ganó : {wins}/{k}  ({wins/k*100:.0f}%)")
    print(f"Edge valor final  → prom {avg_val:+.2f}%  mediana {med_val:+.2f}%  "
          f"min {min(edges_val):+.1f}%  máx {max(edges_val):+.1f}%")
    print(f"Edge costo prom.  → prom {avg_cost:+.2f}%")
    print("=" * 60)
    if avg_val > 0.5 and wins / k > 0.55:
        print("→ El Smart DCA tiende a superar al plano (leve pero consistente).")
    elif avg_val < -0.5:
        print("→ El Smart DCA tiende a quedar por debajo del plano.")
    else:
        print("→ Empate: el Smart DCA ≈ DCA plano. El valor está en automatizar, no en el timing.")


if __name__ == "__main__":
    main()
