"""
Exp B — Mean-reversion intradía (15m).

Idea: en marcos cortos BTC tiene reversión a la media (sobre-reacción que se
corrige). Probar Bollinger y RSI reversion en 15m. OJO: a 15m los fees
(0.15%/lado) pesan mucho — el riesgo es que el costo se coma el edge.

Backtest ~180 días de 15m. La anualización del Sharpe usa el factor horario del
motor, pero la comparación strat-vs-B&H es consistente (mismo factor).

Uso: python run_research_intraday.py
"""

from run_backtest import fetch_history
from backtest import run_backtest
from signals_research import bollinger_reversion_signal, rsi_reversion_signal

SYMBOL, TIMEFRAME, DAYS = "BTC/USDT", "15m", 180


def pct(x):
    return f"{x*100:+.1f}%"


def main():
    df = fetch_history(SYMBOL, TIMEFRAME, DAYS)
    close = df["close"]
    m0 = run_backtest(df, bollinger_reversion_signal(close, 20, 2.0))
    print("\n" + "=" * 66)
    print(f"EXP B — Mean-reversion intradía (15m) — {SYMBOL} {DAYS}d")
    print(f"Buy & Hold: ret {pct(m0['bh_return'])}  Sharpe {m0['bh_sharpe']:.2f}")
    print("=" * 66)
    print(f"{'variante':<30}{'ret':>9}{'Sharpe':>8}{'maxDD':>9}{'trades':>8}")
    print("-" * 66)
    variants = {
        "Bollinger(20, 2.0)": bollinger_reversion_signal(close, 20, 2.0),
        "Bollinger(20, 2.5)": bollinger_reversion_signal(close, 20, 2.5),
        "Bollinger(50, 2.5)": bollinger_reversion_signal(close, 50, 2.5),
        "RSI rev(14, 25/55)": rsi_reversion_signal(close, 14, 25, 55),
        "RSI rev(7, 20/60)": rsi_reversion_signal(close, 7, 20, 60),
    }
    best = (None, -9, None)
    for name, sig in variants.items():
        m = run_backtest(df, sig)
        print(f"{name:<30}{pct(m['total_return']):>9}{m['sharpe']:>8.2f}"
              f"{pct(m['max_drawdown']):>9}{m['n_trades']:>8}")
        if m["sharpe"] > best[1]:
            best = (name, m["sharpe"], m)
    print("=" * 66)
    bm = best[2]
    if best[1] > m0["bh_sharpe"] and bm["max_drawdown"] > m0["bh_max_drawdown"]:
        print(f"-> Mejor '{best[0]}' Sharpe {best[1]:.2f} SUPERA al B&H. Vale walk-forward.")
    else:
        print(f"-> Mejor '{best[0]}' Sharpe {best[1]:.2f}: NO supera al B&H.")


if __name__ == "__main__":
    main()
