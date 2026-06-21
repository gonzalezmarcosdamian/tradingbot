"""
orders.py — Validación y envío idempotente de órdenes.

Único módulo con permiso de mandar órdenes reales. Es el puente entre una
decisión YA APROBADA por risk.py y el exchange. NO decide sizing ni stops:
solo ejecuta lo aprobado, de forma segura.

Pilares:
  1. Validación pre-envío local (minNotional, step size, price filter, saldo)
     → rechazamos nosotros con mensaje claro en vez de un error críptico.
  2. Idempotencia: clientOrderId determinístico por intención. Un reintento
     del mismo intent usa el mismo ID → el exchange rechaza el duplicado en
     vez de crear una segunda orden. Evita el doble-fill por timeout.
  3. Robustez post-timeout: un timeout NO significa que la orden falló. Antes
     de concluir, verificamos por clientOrderId si entró.

Soporta market y limit. Limit agrega estados que market no tiene:
parcialmente ejecutada y abierta sin ejecutar. Se manejan explícitamente.
"""

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Optional


class ExchangeClient(Protocol):
    def create_order(self, symbol, type, side, amount, price=None, params=None) -> dict: ...
    def fetch_order(self, client_order_id, symbol) -> dict: ...
    def fetch_base_balance(self, symbol) -> float: ...
    def fetch_quote_balance(self, symbol) -> float: ...
    def market_filters(self, symbol) -> dict:
        """Devuelve {'min_notional', 'step_size', 'min_price', 'max_price'}."""
        ...


class OrderOutcome(Enum):
    FILLED = "filled"            # ejecutada (total)
    PARTIAL = "partial"          # parcialmente ejecutada (limit)
    OPEN = "open"               # abierta esperando precio (limit)
    REJECTED = "rejected"        # rechazada en validación o por el exchange
    UNCERTAIN = "uncertain"      # no se pudo confirmar → reconciliar


@dataclass
class OrderRequest:
    symbol: str
    side: str                    # "buy" | "sell"
    type: str                    # "market" | "limit"
    amount: float                # cantidad en base (BTC)
    price: Optional[float] = None  # requerido para limit
    intent_id: str = ""          # identifica la intención (para idempotencia)


@dataclass
class OrderResult:
    outcome: OrderOutcome
    reason: str
    client_order_id: str = ""
    filled: float = 0.0
    average_price: Optional[float] = None
    raw: Optional[dict] = None


# ── Idempotencia ──────────────────────────────────────────────────

def make_client_order_id(req: OrderRequest) -> str:
    """ID determinístico a partir de la intención.

    Mismo intent → mismo ID → reintento seguro. El intent_id debe ser estable
    para una misma decisión (ej. símbolo+lado+timestamp de la vela que la gatilló).
    """
    base = f"{req.symbol}|{req.side}|{req.type}|{req.amount}|{req.price}|{req.intent_id}"
    digest = hashlib.sha256(base.encode()).hexdigest()[:20]
    # Prefijo 'bot-' para distinguir órdenes del bot en el exchange
    return f"bot-{digest}"


# ── Validación pre-envío ──────────────────────────────────────────

def _round_to_step(amount: float, step: float) -> float:
    """Trunca la cantidad al múltiplo de step permitido (no redondea hacia arriba)."""
    if step <= 0:
        return amount
    return (int(amount / step)) * step


def validate_order(req: OrderRequest, exchange: ExchangeClient) -> Optional[str]:
    """Valida localmente. Devuelve None si OK, o un string con el motivo de rechazo."""
    if req.side not in ("buy", "sell"):
        return f"side inválido: {req.side}"
    if req.type not in ("market", "limit"):
        return f"type inválido: {req.type}"
    if req.type == "limit" and (req.price is None or req.price <= 0):
        return "orden limit requiere price > 0"
    if req.amount <= 0:
        return "amount debe ser > 0"

    filters = exchange.market_filters(req.symbol)
    step = filters.get("step_size", 0)
    adjusted = _round_to_step(req.amount, step)
    if adjusted <= 0:
        return f"amount {req.amount} menor que el step size {step}"

    # Notional mínimo (precio de referencia: limit usa su price; market usa balance)
    ref_price = req.price
    if ref_price is None:
        # Para market no tenemos precio en la request; lo aproxima quien llama.
        # Si no hay forma de estimar, saltamos el chequeo de notional acá.
        ref_price = filters.get("ref_price")
    if ref_price:
        notional = adjusted * ref_price
        if notional < filters.get("min_notional", 0):
            return (f"notional {notional:.2f} bajo el mínimo "
                    f"{filters.get('min_notional')}")
        if filters.get("min_price") and ref_price < filters["min_price"]:
            return "precio bajo el mínimo permitido"
        if filters.get("max_price") and ref_price > filters["max_price"]:
            return "precio sobre el máximo permitido"

    # Saldo suficiente
    if req.side == "buy":
        quote = exchange.fetch_quote_balance(req.symbol)
        needed = adjusted * (ref_price or 0)
        if ref_price and needed > quote:
            return f"saldo insuficiente: necesita {needed:.2f}, tiene {quote:.2f}"
    else:  # sell
        base = exchange.fetch_base_balance(req.symbol)
        if adjusted > base + 1e-12:
            return f"base insuficiente: vende {adjusted}, tiene {base}"

    return None


# ── Envío idempotente ─────────────────────────────────────────────

# Errores que significan rechazo DEFINITIVO (la orden NO entró): no son
# incertidumbre de red, así que no deben gatillar reconciliación/halt.
_DEFINITE_REJECTION_TYPES = {
    "InsufficientFunds", "InvalidOrder", "BadRequest", "BadSymbol",
    "NotSupported", "ArgumentsRequired",
}
_DEFINITE_REJECTION_MSGS = (
    "insufficient", "min notional", "minimum notional", "filter failure",
    "invalid quantity", "lot_size", "lot size", "precision",
)


def _is_definite_rejection(e: Exception) -> bool:
    """True si el error indica que la orden fue rechazada con certeza (no entró)."""
    if type(e).__name__ in _DEFINITE_REJECTION_TYPES:
        return True
    msg = str(e).lower()
    return any(s in msg for s in _DEFINITE_REJECTION_MSGS)


def _classify(order: dict) -> OrderResult:
    """Traduce la respuesta del exchange a un OrderResult."""
    status = order.get("status")
    filled = order.get("filled", 0.0) or 0.0
    amount = order.get("amount", 0.0) or 0.0
    coid = order.get("clientOrderId", "")
    avg = order.get("average")

    if status == "closed" or (amount > 0 and filled >= amount - 1e-12):
        return OrderResult(OrderOutcome.FILLED, "ejecutada", coid, filled, avg, order)
    if status == "open" and filled > 0:
        return OrderResult(OrderOutcome.PARTIAL, "parcialmente ejecutada", coid, filled, avg, order)
    if status == "open":
        return OrderResult(OrderOutcome.OPEN, "abierta esperando precio", coid, filled, avg, order)
    if status == "canceled":
        return OrderResult(OrderOutcome.REJECTED, "cancelada por el exchange", coid, filled, avg, order)
    return OrderResult(OrderOutcome.UNCERTAIN, f"estado desconocido: {status}", coid, filled, avg, order)


def send_order(req: OrderRequest, exchange: ExchangeClient) -> OrderResult:
    """Envía una orden de forma idempotente y robusta a timeouts.

    NO genera sizing ni stops: ejecuta lo que recibe. Devuelve un OrderResult
    con outcome claro. UNCERTAIN significa: no pudimos confirmar, reconciliar.
    """
    # 1. Validación local
    err = validate_order(req, exchange)
    if err:
        return OrderResult(OrderOutcome.REJECTED, f"validación: {err}")

    coid = make_client_order_id(req)
    filters = exchange.market_filters(req.symbol)
    amount = _round_to_step(req.amount, filters.get("step_size", 0))
    params = {"clientOrderId": coid}

    # 2. ¿Ya existe esta orden? (idempotencia: reintento del mismo intent)
    try:
        existing = exchange.fetch_order(coid, req.symbol)
        if existing:
            return _classify(existing)
    except Exception:
        # No existe todavía (lo normal en el primer envío). Seguimos.
        pass

    # 3. Enviar
    try:
        order = exchange.create_order(
            req.symbol, req.type, req.side, amount, req.price, params
        )
        return _classify(order)
    except Exception as e:
        # 4a. Rechazo definitivo (saldo, filtros, orden inválida): NO entró.
        #     Es REJECTED, no incierto → no dispara reconciliación/halt.
        if _is_definite_rejection(e):
            return OrderResult(OrderOutcome.REJECTED, f"rechazada por el exchange: {e}", coid)
        # 4b. Timeout / error de red: NO asumir que falló. Verificar por ID.
        try:
            check = exchange.fetch_order(coid, req.symbol)
            if check:
                return _classify(check)
        except Exception:
            pass
        return OrderResult(
            OrderOutcome.UNCERTAIN,
            f"envío sin confirmar ({e}); requiere reconciliación",
            coid,
        )
