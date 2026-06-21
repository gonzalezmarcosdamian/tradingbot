"""
test_evaluator.py — Tests del evaluador de paper trading.

Verifica que lee bien los trades cerrados del journal y calcula las métricas.
"""

from journal import Journal, EventType
from evaluator import evaluate, closed_trades, format_report


def _journal(tmp_path):
    return Journal(db_path=str(tmp_path / "j.db"), text_path=str(tmp_path / "j.log"))


def test_sin_trades_da_cero(tmp_path):
    m = evaluate(_journal(tmp_path))
    assert m["n_trades"] == 0 and m["realized_pnl"] == 0.0 and m["win_rate"] == 0.0


def test_cuenta_trades_y_winrate(tmp_path):
    j = _journal(tmp_path)
    # Dos ganadores, un perdedor
    j.log(EventType.ORDER, "trade cerrado", {"closed_trade": True, "pnl": 100.0, "pnl_pct": 0.10})
    j.log(EventType.ORDER, "trade cerrado", {"closed_trade": True, "pnl": 50.0, "pnl_pct": 0.05})
    j.log(EventType.ORDER, "trade cerrado", {"closed_trade": True, "pnl": -30.0, "pnl_pct": -0.03})
    # Un ORDER que NO es trade cerrado: no debe contar
    j.log(EventType.ORDER, "buy → filled", {"filled": 0.01})

    m = evaluate(j)
    assert m["n_trades"] == 3
    assert m["wins"] == 2 and m["losses"] == 1
    assert m["win_rate"] == 2 / 3
    assert m["realized_pnl"] == 120.0
    assert m["best"] == 100.0 and m["worst"] == -30.0


def test_format_report_no_rompe(tmp_path):
    j = _journal(tmp_path)
    j.log(EventType.ORDER, "trade cerrado", {"closed_trade": True, "pnl": 10.0, "pnl_pct": 0.01})
    assert "[eval]" in format_report(evaluate(j))


def test_closed_trades_filtra(tmp_path):
    j = _journal(tmp_path)
    j.log(EventType.ORDER, "trade cerrado", {"closed_trade": True, "pnl": 1.0})
    j.log(EventType.SIGNAL, "señal", {"foo": 1})
    assert len(closed_trades(j)) == 1
