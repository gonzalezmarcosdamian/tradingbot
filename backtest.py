"""
backtest.py — Motor de backtest long-only con costos realistas.

Puntos clave de honestidad:
  - Ejecución en t+1: la señal generada con datos hasta la vela t se aplica
    a partir de la vela siguiente (shift 1). Evita look-ahead bias.
  - Costos: se cobra fee + slippage en CADA cambio de posición (entrada y salida).
  - Benchmark: siempre se compara contra buy-and-hold del mismo período.
"""

import numpy as np
import pandas as pd

# Costos por operación (cada lado: entrada o salida)
FEE = 0.001        # 0.1% taker Binance spot
SLIPPAGE = 0.0005  # 0.05% estimado
COST_PER_SIDE = FEE + SLIPPAGE

# Velas de 1h por año, para anualizar
BARS_PER_YEAR = 24 * 365


def run_backtest(df: pd.DataFrame, signal: pd.Series) -> dict:
    """Corre un backtest sobre un DataFrame con columna 'close' y una señal.

    Devuelve un dict con la curva de equity y las métricas.
    """
    close = df["close"].reset_index(drop=True)
    signal = signal.reset_index(drop=True)

    # Posición efectiva: la señal de t se ejecuta en t+1 → shift(1)
    position = signal.shift(1).fillna(0)

    # Retorno de mercado por barra
    market_ret = close.pct_change().fillna(0)

    # Retorno de la estrategia: solo capturamos retorno cuando estamos posicionados
    strat_ret = position * market_ret

    # Costos: se aplican cuando la posición cambia (abs del delta de posición)
    trades = position.diff().abs().fillna(0)
    cost = trades * COST_PER_SIDE
    strat_ret_net = strat_ret - cost

    # Curvas de equity (base 1.0)
    equity = (1 + strat_ret_net).cumprod()
    benchmark = (1 + market_ret).cumprod()

    metrics = _compute_metrics(strat_ret_net, equity, market_ret, benchmark, position, trades)
    metrics["equity"] = equity
    metrics["benchmark"] = benchmark
    return metrics


def _compute_metrics(strat_ret, equity, market_ret, benchmark, position, trades) -> dict:
    n_bars = len(strat_ret)
    if n_bars == 0:
        return {}

    total_return = equity.iloc[-1] - 1
    bh_return = benchmark.iloc[-1] - 1

    # Anualización
    years = n_bars / BARS_PER_YEAR
    ann_return = (equity.iloc[-1]) ** (1 / years) - 1 if years > 0 else 0
    bh_ann_return = (benchmark.iloc[-1]) ** (1 / years) - 1 if years > 0 else 0

    # Sharpe anualizado (rf = 0). Std de los retornos por barra.
    std = strat_ret.std()
    sharpe = (strat_ret.mean() / std * np.sqrt(BARS_PER_YEAR)) if std > 0 else 0
    bh_std = market_ret.std()
    bh_sharpe = (market_ret.mean() / bh_std * np.sqrt(BARS_PER_YEAR)) if bh_std > 0 else 0

    # Max drawdown
    max_dd = _max_drawdown(equity)
    bh_max_dd = _max_drawdown(benchmark)

    # Trades: cada entrada+salida son 2 cambios de posición → nº de trades ≈ cambios/2
    n_position_changes = int(trades[trades > 0].count())
    n_trades = n_position_changes // 2 if n_position_changes >= 2 else n_position_changes

    # Exposición: % de barras estando comprado
    exposure = (position > 0).mean()

    # Win rate por trade: agrupamos retornos en bloques de posición continua
    win_rate = _trade_win_rate(strat_ret, position)

    return {
        "total_return": total_return,
        "bh_return": bh_return,
        "ann_return": ann_return,
        "bh_ann_return": bh_ann_return,
        "sharpe": sharpe,
        "bh_sharpe": bh_sharpe,
        "max_drawdown": max_dd,
        "bh_max_drawdown": bh_max_dd,
        "n_trades": n_trades,
        "exposure": exposure,
        "win_rate": win_rate,
    }


def _max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    return drawdown.min()


def _trade_win_rate(strat_ret: pd.Series, position: pd.Series) -> float:
    """Calcula el % de trades ganadores agrupando bloques de posición continua."""
    in_pos = position > 0
    if not in_pos.any():
        return 0.0

    # Identificar bloques contiguos de posición abierta
    block_id = (in_pos != in_pos.shift()).cumsum()
    trade_returns = []
    for _, grp in strat_ret[in_pos].groupby(block_id[in_pos]):
        # Retorno compuesto del bloque
        trade_returns.append((1 + grp).prod() - 1)

    if not trade_returns:
        return 0.0
    wins = sum(1 for r in trade_returns if r > 0)
    return wins / len(trade_returns)
