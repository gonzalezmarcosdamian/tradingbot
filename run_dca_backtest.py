"""
run_dca_backtest.py — Backtest Smart DCA vs DCA plano (rolling ~12 meses).

Replica la lógica EXACTA del DCA en vivo (reusa dca.analyze / dca.decide), sin
look-ahead: en cada compra solo mira los precios hasta esa fecha. Compara contra
un DCA plano (misma plata, cuotas iguales) y reporta BTC acumulado, costo
promedio, valor final y el "edge".

Uso:
  python run_dca_backtest.py

Baja data pública de Binance (sin claves).
"""

import sys
import ccxt

from dca import DCAConfig, DCAState, analyze, decide, maybe_reset_period

SYMBOL = "BTC/USDT"
TIMEFRAME = "1d"
DAYS = 400                 # ~13 meses: 12 de compras + warmup para la media
WARMUP = 35                # días iniciales sin comprar (para tener MA/RSI)
STEP_DAYS = 7              # compra semanal
DAY = 86400

PERIOD_BUDGET = 100.0      # presupuesto por período (mes)
BUYS_PER_PERIOD = 4        # 4 compras semanales por período


def fetch_daily(symbol, days):
    ex = ccxt.binance({"enableRateLimit": True})
    ex.load_markets()
    rows = ex.fetch_ohlcv(symbol, TIMEFRAME, limit=days)
    return rows  # [[ts_ms, o, h, l, c, v], ...]


def main():
    print("Bajando data diaria de Binance...", flush=True)
    try:
        rows = fetch_daily(SYMBOL, DAYS)
    except Exception as e:
        print(f"Error bajando data: {e}", file=sys.stderr)
        sys.exit(1)

    closes = [r[4] for r in rows]
    ts = [r[0] // 1000 for r in rows]  # a segundos
    if len(closes) < WARMUP + STEP_DAYS:
        print("Data insuficiente.", file=sys.stderr)
        sys.exit(1)

    config = DCAConfig(
        symbol=SYMBOL,
        period_budget=PERIOD_BUDGET,
        buys_per_period=BUYS_PER_PERIOD,
        period_seconds=STEP_DAYS * BUYS_PER_PERIOD * DAY,  # período = 4 semanas
        timeframe="1d", ma_period=30, rsi_period=14,
        sensitivity=5.0, rsi_sensitivity=1.0, min_mult=0.3, max_mult=2.5,
        smart=True,
    )
    flat_quote = PERIOD_BUDGET / BUYS_PER_PERIOD  # cuota fija del DCA plano

    state = DCAState()
    smart_btc = smart_spent = 0.0
    flat_btc = flat_spent = 0.0
    n_buys = 0
    mults = []

    # Eventos de compra: cada STEP_DAYS, desde el warmup hasta el final.
    for i in range(WARMUP, len(closes), STEP_DAYS):
        now = ts[i]
        price = closes[i]
        closes_so_far = closes[: i + 1]

        state = maybe_reset_period(state, config, now)
        a = analyze(closes_so_far, price, config)
        d = decide(config, state, now, available_cash=1e12, multiplier=a.multiplier)
        if not d.should_buy:
            continue

        # Smart
        s_btc = d.quote_amount / price
        state.spent_this_period += d.quote_amount
        state.buys_this_period += 1
        state.last_buy_ts = now
        smart_btc += s_btc
        smart_spent += d.quote_amount
        mults.append(a.multiplier)

        # Plano (mismo momento, cuota fija)
        flat_btc += flat_quote / price
        flat_spent += flat_quote
        n_buys += 1

    final_price = closes[-1]
    smart_avg = smart_spent / smart_btc if smart_btc else 0
    flat_avg = flat_spent / flat_btc if flat_btc else 0
    smart_val = smart_btc * final_price
    flat_val = flat_btc * final_price
    edge_cost = (flat_avg - smart_avg) / flat_avg * 100 if flat_avg else 0
    edge_val = (smart_val - flat_val) / flat_val * 100 if flat_val else 0

    span_days = (ts[-1] - ts[WARMUP]) / DAY
    print(f"\n{'='*64}")
    print(f"BACKTEST DCA — {SYMBOL}  ({span_days:.0f} días, {n_buys} compras semanales)")
    print(f"Precio inicial {closes[WARMUP]:,.0f} → final {final_price:,.0f}  "
          f"({(final_price/closes[WARMUP]-1)*100:+.1f}%)")
    print(f"Múltiplo smart: min {min(mults):.2f}  máx {max(mults):.2f}  "
          f"prom {sum(mults)/len(mults):.2f}")
    print("=" * 64)
    print(f"{'':<16}{'gastado':>12}{'BTC acum.':>14}{'costo prom.':>14}{'valor final':>14}")
    print("-" * 64)
    print(f"{'Smart DCA':<16}{smart_spent:>11,.0f}{smart_btc:>14.6f}{smart_avg:>13,.0f}{smart_val:>13,.0f}")
    print(f"{'DCA plano':<16}{flat_spent:>11,.0f}{flat_btc:>14.6f}{flat_avg:>13,.0f}{flat_val:>13,.0f}")
    print("=" * 64)
    print(f"Edge en costo promedio : {edge_cost:+.2f}%  (positivo = smart compró más barato)")
    print(f"Edge en valor final    : {edge_val:+.2f}%  (positivo = smart terminó con más)")
    print(f"BTC extra del smart     : {smart_btc - flat_btc:+.6f} BTC "
          f"(${(smart_btc - flat_btc)*final_price:+,.0f})")
    print("=" * 64)
    if edge_val > 0:
        print("→ El Smart DCA superó al plano en este período.")
    else:
        print("→ El Smart DCA NO superó al plano en este período.")


if __name__ == "__main__":
    main()
