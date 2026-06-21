"""
evaluator.py — Mide el desempeño del paper trading desde el journal.

Lee los trades cerrados que registra bot.py (eventos ORDER con
closed_trade=True) y calcula métricas: nº de trades, win rate, PnL realizado,
retorno medio por trade, mejor y peor. Sirve para dos cosas:
  - El bot lo imprime periódicamente a stdout (visible en los logs).
  - Se puede correr a mano: `python evaluator.py` (lee DATA_DIR).

Diseño testeable: evaluate() recibe un journal (real o falso) y no toca la red.
"""

import sys

from journal import Journal, EventType


def closed_trades(journal) -> list:
    """Trades cerrados registrados (payloads con closed_trade=True)."""
    events = journal.query(EventType.ORDER, limit=100_000)
    return [e.payload for e in events
            if isinstance(e.payload, dict) and e.payload.get("closed_trade")]


def evaluate(journal) -> dict:
    """Métricas de performance sobre los trades cerrados."""
    trades = closed_trades(journal)
    n = len(trades)
    pnls = [float(t.get("pnl", 0.0)) for t in trades]
    pcts = [float(t.get("pnl_pct", 0.0)) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    return {
        "n_trades": n,
        "realized_pnl": sum(pnls),
        "wins": wins,
        "losses": n - wins,
        "win_rate": wins / n if n else 0.0,
        "avg_pnl_pct": (sum(pcts) / n) if n else 0.0,
        "best": max(pnls, default=0.0),
        "worst": min(pnls, default=0.0),
    }


def format_report(m: dict) -> str:
    return (f"[eval] trades={m['n_trades']} winrate={m['win_rate']:.0%} "
            f"pnl_realizado={m['realized_pnl']:+.2f} "
            f"avg/trade={m['avg_pnl_pct']:+.2%} "
            f"best={m['best']:+.2f} worst={m['worst']:+.2f}")


def main():
    journal = Journal()
    m = evaluate(journal)
    print(format_report(m))
    if m["n_trades"] == 0:
        print("(sin trades cerrados todavía)", file=sys.stderr)


if __name__ == "__main__":
    main()
