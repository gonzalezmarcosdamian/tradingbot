"""
killswitch.py — Panic-close + detención del bot.

Propósito (CRÍTICO, ver ARCHITECTURE.md 5.2):
  Un único comando que cierra TODAS las posiciones y detiene el bot. Debe
  funcionar aunque el resto del bot esté colgado, así que se mantiene
  deliberadamente liviano y SIN depender de la maquinaria de órdenes normal
  (que podría ser justo lo que está trabado).

Dos mecanismos independientes:

  1. HALT FLAG (archivo en disco): su sola presencia significa "no operar".
     - Sobrevive a reinicios del proceso (un crash + restart NO reanuda trading).
     - Es la fuente de verdad que el loop principal consulta antes de cada orden.
     - Persistido en DATA_DIR (en Railway, el Volume) igual que journal/estado.

  2. PANIC-CLOSE: cancela órdenes abiertas y vende toda la posición a mercado.
     - Hace engage del halt PRIMERO: aunque la venta falle, el bot queda detenido.
     - Reintenta las operaciones de red; reporta qué pudo y qué no.

Filosofía: ante la duda, detener. Es preferible un bot apagado de más que uno
operando cuando no debería.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, Optional


# ── Interfaz mínima del exchange para el panic-close ───────────────
# A propósito chica: el kill-switch no debe arrastrar dependencias pesadas.

class PanicExchange(Protocol):
    def cancel_all_orders(self, symbol: str) -> list:
        """Cancela todas las órdenes abiertas del símbolo. Devuelve las canceladas."""
        ...

    def fetch_base_balance(self, symbol: str) -> float:
        """Balance real del activo base (ej. BTC) en la cuenta dedicada."""
        ...

    def create_market_sell(self, symbol: str, amount: float) -> dict:
        """Vende `amount` de base a mercado. Devuelve la respuesta del exchange."""
        ...

    def market_filters(self, symbol: str) -> dict:
        """Filtros del mercado: al menos {'step_size', 'min_notional', 'ref_price'}."""
        ...


# ── HALT FLAG (archivo en disco) ───────────────────────────────────

def _data_dir() -> str:
    """Carpeta de datos. En Railway, DATA_DIR apunta al Volume persistente."""
    d = os.getenv("DATA_DIR", "./data")
    os.makedirs(d, exist_ok=True)
    return d


def halt_file_path() -> str:
    return os.path.join(_data_dir(), "HALT")


def is_halted() -> bool:
    """True si el bot está detenido. El loop principal lo consulta SIEMPRE
    antes de operar."""
    return os.path.exists(halt_file_path())


def engage_halt(reason: str) -> str:
    """Detiene el bot dejando el flag en disco. Idempotente y a prueba de
    reinicios: mientras el archivo exista, el bot no opera.

    No relanza si falla la escritura por algo tan grave que ni podemos crear
    el archivo: en ese caso el llamador igual debería abortar el proceso.
    """
    ts = datetime.now(timezone.utc).isoformat()
    path = halt_file_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{ts}\n{reason}\n")
    return path


def clear_halt() -> bool:
    """Levanta el halt (reactivación MANUAL y deliberada). Devuelve True si
    había un halt que quitar. Nunca se llama automáticamente: reactivar es
    siempre una decisión humana."""
    path = halt_file_path()
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def halt_reason() -> Optional[str]:
    """Devuelve el motivo del halt activo, o None si no hay halt."""
    path = halt_file_path()
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    return lines[1] if len(lines) > 1 else ""


# ── PANIC-CLOSE ────────────────────────────────────────────────────

@dataclass
class PanicReport:
    halted: bool                       # ¿quedó el halt activado?
    orders_canceled: int = 0
    sold_amount: float = 0.0           # cantidad de base vendida
    success: bool = False              # ¿se logró aplanar la posición?
    steps: list = field(default_factory=list)  # bitácora legible de lo hecho
    errors: list = field(default_factory=list)


def _round_to_step(amount: float, step: float) -> float:
    """Trunca al múltiplo de step (hacia abajo). Igual criterio que orders.py."""
    if step <= 0:
        return amount
    return int(amount / step) * step


def _retry(fn, attempts: int, report: PanicReport, label: str):
    """Ejecuta fn con reintentos. Registra el resultado en el report.
    Devuelve (ok, valor)."""
    last_err = None
    for i in range(attempts):
        try:
            return True, fn()
        except Exception as e:  # red inestable: reintentar es lo correcto acá
            last_err = e
            report.steps.append(f"{label}: intento {i + 1} falló ({e})")
    report.errors.append(f"{label}: agotados {attempts} intentos ({last_err})")
    return False, None


def panic_close(
    exchange: PanicExchange,
    symbol: str = "BTC/USDT",
    reason: str = "panic-close manual",
    attempts: int = 3,
) -> PanicReport:
    """Cierra todo y detiene el bot.

    Orden de operaciones pensado para fallar seguro:
      1. ENGAGE HALT primero. Si todo lo demás falla, el bot igual queda parado.
      2. Cancelar órdenes abiertas (si quedan limit colgadas, liberan la base).
      3. Leer balance real de base y venderlo a mercado (aplanar la posición).

    Devuelve un PanicReport con el detalle. success=True solo si la posición
    quedó efectivamente en ~0.
    """
    report = PanicReport(halted=False)

    # 1. Halt PRIMERO: la detención no depende de que la venta salga bien.
    try:
        engage_halt(reason)
        report.halted = True
        report.steps.append(f"halt activado: {reason}")
    except OSError as e:
        report.errors.append(f"no se pudo escribir el halt flag: {e}")

    # 2. Cancelar órdenes abiertas
    ok, canceled = _retry(
        lambda: exchange.cancel_all_orders(symbol), attempts, report, "cancel_all_orders"
    )
    if ok:
        report.orders_canceled = len(canceled or [])
        report.steps.append(f"órdenes canceladas: {report.orders_canceled}")

    # 3. Vender toda la base a mercado
    ok, base = _retry(
        lambda: exchange.fetch_base_balance(symbol), attempts, report, "fetch_base_balance"
    )
    if not ok:
        # No sabemos cuánto hay: no podemos garantizar el cierre. Quedó halted.
        report.success = False
        return report

    base = base or 0.0
    filters = {}
    try:
        filters = exchange.market_filters(symbol) or {}
    except Exception as e:
        report.steps.append(f"market_filters falló, se vende sin redondeo ({e})")

    step = filters.get("step_size", 0)
    sell_amount = _round_to_step(base, step)

    if sell_amount <= 0:
        # Ya estamos planos (o el polvo es menor al step: nada vendible).
        report.success = True
        report.steps.append(f"sin posición vendible (base={base})")
        return report

    ok, _ = _retry(
        lambda: exchange.create_market_sell(symbol, sell_amount),
        attempts, report, "create_market_sell",
    )
    if ok:
        report.sold_amount = sell_amount
        report.success = True
        report.steps.append(f"vendido a mercado: {sell_amount} de base")
    else:
        report.success = False  # quedó halted, pero la posición NO se cerró

    return report
