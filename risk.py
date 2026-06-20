"""
risk.py — Gestión de riesgo. Lógica PURA (no toca el exchange).

Recibe números y estado, devuelve decisiones. El envío real de órdenes lo
hace orders.py. Separado así para poder testearlo a fondo sin riesgo.

Filosofía de salidas (decidida en diseño):
  - La SALIDA NORMAL la maneja la estrategia (cruce de medias a la baja).
  - El stop-loss es una RED DE SEGURIDAD ante catástrofe: solo se dispara si
    el precio cae fuerte antes de que la media reaccione. Configurable y
    desactivable, pero presente por prudencia.
  - El take-profit, por la misma razón, queda OPCIONAL (off por defecto):
    cerrar en TP contradiría "dejar correr hasta que la estrategia salga".

Defaults conservadores a propósito: mejor demasiado cauto y que el operador
lo afloje, que agresivo por defecto.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Decision(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class RiskConfig:
    capital_fraction: float = 0.95   # % del disponible a usar por trade
    stop_loss_pct: float = 0.02      # 2% bajo la entrada (red de seguridad)
    take_profit_pct: float = 0.04    # 4% sobre la entrada (opcional, ver flag)
    use_take_profit: bool = False    # off: la estrategia maneja la salida
    daily_loss_limit: float = 0.05   # -5% en el día corta nuevas entradas
    max_exposure: float = 1.0        # 100%: una posición, sin apalancamiento

    def __post_init__(self):
        # Validaciones de cordura de la config
        assert 0 < self.capital_fraction <= 1, "capital_fraction debe estar en (0, 1]"
        assert 0 < self.stop_loss_pct < 1, "stop_loss_pct fuera de rango"
        assert 0 < self.take_profit_pct < 1, "take_profit_pct fuera de rango"
        assert 0 < self.daily_loss_limit < 1, "daily_loss_limit fuera de rango"
        assert 0 < self.max_exposure <= 1, "max_exposure debe estar en (0, 1]"


@dataclass
class RiskState:
    """Estado vivo del riesgo. Lo persiste state.py en la práctica."""
    day: date = field(default_factory=date.today)
    day_start_equity: float = 0.0    # equity al inicio del día
    realized_pnl_today: float = 0.0  # PnL realizado acumulado del día
    in_position: bool = False
    position_value: float = 0.0      # valor actual comprometido

    def roll_day_if_needed(self, today: date, current_equity: float):
        """Reinicia los contadores diarios al cambiar de día."""
        if today != self.day:
            self.day = today
            self.day_start_equity = current_equity
            self.realized_pnl_today = 0.0


@dataclass
class OrderProposal:
    side: str        # "buy" o "sell"
    available_cash: float
    current_equity: float
    price: float


@dataclass
class RiskResult:
    decision: Decision
    reason: str
    size_quote: float = 0.0   # monto en USDT a operar (si aprobado)
    stop_price: float | None = None
    take_profit_price: float | None = None


def _daily_loss_breached(state: RiskState, config: RiskConfig) -> bool:
    """True si la pérdida del día ya superó el límite (circuit breaker)."""
    if state.day_start_equity <= 0:
        return False
    drawdown = state.realized_pnl_today / state.day_start_equity
    return drawdown <= -config.daily_loss_limit


def approve_order(
    proposal: OrderProposal,
    state: RiskState,
    config: RiskConfig,
    today: date | None = None,
) -> RiskResult:
    """Función guardiana: TODA orden pasa por acá antes de enviarse.

    Devuelve APPROVED con sizing y stops, o REJECTED con el motivo.
    """
    today = today or date.today()
    state.roll_day_if_needed(today, proposal.current_equity)

    # ── Salidas (sell): se permiten casi siempre. Querer salir es seguro. ──
    if proposal.side == "sell":
        if not state.in_position:
            return RiskResult(Decision.REJECTED, "No hay posición para vender")
        return RiskResult(Decision.APPROVED, "Salida aprobada", size_quote=state.position_value)

    # ── Entradas (buy): acá aplican TODAS las restricciones de riesgo ──

    # 1. Circuit breaker diario
    if _daily_loss_breached(state, config):
        return RiskResult(
            Decision.REJECTED,
            f"Circuit breaker: pérdida diaria superó {config.daily_loss_limit:.0%}",
        )

    # 2. Ya estamos en posición (long-only, una a la vez)
    if state.in_position:
        return RiskResult(Decision.REJECTED, "Ya hay una posición abierta")

    # 3. Exposición máxima
    max_allowed = proposal.current_equity * config.max_exposure
    if state.position_value >= max_allowed:
        return RiskResult(Decision.REJECTED, "Exposición máxima alcanzada")

    # 4. Sizing
    size_quote = proposal.available_cash * config.capital_fraction
    if size_quote <= 0:
        return RiskResult(Decision.REJECTED, "Sin capital disponible para operar")

    # No exceder la exposición máxima con esta orden
    room = max_allowed - state.position_value
    if size_quote > room:
        size_quote = room

    # 5. Stops (precios de referencia)
    stop_price = proposal.price * (1 - config.stop_loss_pct)
    tp_price = (
        proposal.price * (1 + config.take_profit_pct)
        if config.use_take_profit
        else None
    )

    return RiskResult(
        Decision.APPROVED,
        "Entrada aprobada",
        size_quote=size_quote,
        stop_price=stop_price,
        take_profit_price=tp_price,
    )
