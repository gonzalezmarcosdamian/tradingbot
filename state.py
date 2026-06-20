"""
state.py — Persistencia y reconciliación de estado.

CONTEXTO: cuenta DEDICADA al bot (sin holdings personales del usuario).
  Como la cuenta es de uso exclusivo del bot, el balance real del activo base
  (BTC) ES una fuente de verdad válida sobre la posición del bot. El bot lleva
  además su propia contabilidad interna (por clientOrderId) y reconcile() cruza
  ambas para detectar divergencias.

  (Nota de diseño: si en el futuro la cuenta pasara a compartirse con holdings
  personales, habría que desactivar la verificación contra balance total, porque
  el BTC personal contaminaría la comparación.)

Reconciliación:
  Al arrancar, el bot consulta el estado REAL de SUS órdenes conocidas (por
  clientOrderId) en el exchange y ajusta su contabilidad. El exchange siempre
  gana. Ante cualquier discrepancia que no pueda resolver con confianza →
  SAFE-HALT: no opera y alerta para intervención humana.

Diseño testeable:
  reconcile() recibe un cliente de exchange con una interfaz mínima
  (fetch_order). Los tests usan un exchange falso; no se toca Binance real.
"""

import sqlite3
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Protocol


# ── Interfaz mínima del exchange (para poder mockear en tests) ─────

class ExchangeClient(Protocol):
    def fetch_order(self, client_order_id: str, symbol: str) -> dict:
        """Devuelve el estado de una orden. Debe incluir al menos:
        {'status': 'closed'|'open'|'canceled', 'filled': float,
         'average': float|None, 'side': 'buy'|'sell'}
        """
        ...

    def fetch_base_balance(self, symbol: str) -> float:
        """Devuelve el balance real del activo base (ej. BTC) en la cuenta.
        Válido como fuente de verdad porque la cuenta es DEDICADA al bot.
        """
        ...


# ── Modelo de estado ──────────────────────────────────────────────

@dataclass
class BotState:
    """Contabilidad interna del bot. En cuenta dedicada se cruza contra el
    balance real del exchange durante la reconciliación."""
    in_position: bool = False
    base_qty: float = 0.0          # BTC que el bot considera SUYO
    avg_entry_price: float = 0.0   # precio promedio de entrada
    quote_invested: float = 0.0    # USDT invertidos en la posición actual
    known_orders: list = field(default_factory=list)  # clientOrderIds conocidos
    updated_at: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(s: str) -> "BotState":
        return BotState(**json.loads(s))


@dataclass
class ReconcileReport:
    safe_to_trade: bool
    discrepancies: list
    state: BotState


# ── Persistencia (SQLite) ─────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- fila única
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS known_orders (
    client_order_id TEXT PRIMARY KEY,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class StateStore:
    def __init__(self, db_path: str | None = None):
        import os
        if db_path is None:
            # En Railway, DATA_DIR apunta al Volume persistente. En local, ./data
            base = os.getenv("DATA_DIR", "./data")
            db_path = os.path.join(base, "bot.db")
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def save_state(self, state: BotState):
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO bot_state (id, state_json, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json, "
            "updated_at=excluded.updated_at",
            (state.to_json(), state.updated_at),
        )
        self.conn.commit()

    def load_state(self) -> BotState:
        row = self.conn.execute(
            "SELECT state_json FROM bot_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return BotState()  # estado limpio si es la primera vez
        return BotState.from_json(row[0])

    def record_order(self, client_order_id, side, qty, price, status):
        self.conn.execute(
            "INSERT INTO known_orders "
            "(client_order_id, side, qty, price, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(client_order_id) DO UPDATE SET status=excluded.status",
            (client_order_id, side, qty, price, status,
             datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


# ── Reconciliación ────────────────────────────────────────────────

def reconcile(
    state: BotState,
    exchange: ExchangeClient,
    symbol: str = "BTC/USDT",
    balance_tolerance: float = 0.005,  # 0.5%: absorbe fees/redondeo
) -> ReconcileReport:
    """Reconcilia el estado del bot contra la realidad del exchange.

    Dos verificaciones:
      1. Audita el estado real de las órdenes conocidas (por clientOrderId).
      2. Cruza la contabilidad interna (base_qty) contra el balance REAL del
         exchange (válido porque la cuenta es dedicada al bot).

    El exchange siempre gana. Ante incertidumbre → safe_to_trade=False.
    """
    discrepancies = []

    # ── 1. Auditoría de órdenes conocidas ──────────────────────────
    for oid in state.known_orders:
        try:
            order = exchange.fetch_order(oid, symbol)
        except Exception as e:
            discrepancies.append(
                {"order": oid, "issue": f"no se pudo consultar: {e}", "severity": "halt"}
            )
            continue

        status = order.get("status")
        filled = order.get("filled", 0.0)

        if status == "open":
            discrepancies.append(
                {"order": oid, "issue": "orden quedó abierta de sesión previa",
                 "severity": "halt"}
            )
        elif status == "canceled" and filled == 0:
            discrepancies.append(
                {"order": oid, "issue": "cancelada sin fill, se descarta",
                 "severity": "info"}
            )

    # ── 2. Verificación contra balance real (cuenta dedicada) ──────
    try:
        real_base = exchange.fetch_base_balance(symbol)
    except Exception as e:
        discrepancies.append(
            {"check": "balance", "issue": f"no se pudo leer balance: {e}",
             "severity": "halt"}
        )
        real_base = None

    if real_base is not None:
        believed = state.base_qty
        # Umbral absoluto pequeño para tratar ~0 sin dividir por cero
        near_zero = max(real_base, believed) < 1e-9

        if near_zero:
            pass  # ambos en cero, nada que reconciliar
        elif believed < 1e-9 and real_base > 1e-9:
            # Bot cree estar fuera, pero hay BTC real → adoptar posición
            discrepancies.append(
                {"check": "balance",
                 "issue": f"exchange tiene {real_base} BTC pero el bot creía estar fuera; "
                          f"se adopta la posición real",
                 "severity": "adopt"}
            )
            state.in_position = True
            state.base_qty = real_base
        elif real_base < 1e-9 and believed > 1e-9:
            # Bot cree tener posición, pero no hay BTC → se vendió mientras caído
            discrepancies.append(
                {"check": "balance",
                 "issue": "el bot creía tener posición pero el exchange no tiene BTC; "
                          "se marca como fuera",
                 "severity": "adopt"}
            )
            state.in_position = False
            state.base_qty = 0.0
            state.quote_invested = 0.0
        else:
            # Ambos tienen BTC: ¿coinciden dentro de tolerancia?
            diff_ratio = abs(real_base - believed) / max(believed, 1e-9)
            if diff_ratio <= balance_tolerance:
                # Coincide; alineamos al valor real del exchange
                state.base_qty = real_base
            else:
                # Diferencia inexplicable → no operar
                discrepancies.append(
                    {"check": "balance",
                     "issue": f"discrepancia de balance: bot cree {believed} BTC, "
                              f"exchange tiene {real_base} BTC (diff {diff_ratio:.1%})",
                     "severity": "halt"}
                )

    safe = not any(d["severity"] == "halt" for d in discrepancies)

    return ReconcileReport(
        safe_to_trade=safe,
        discrepancies=discrepancies,
        state=state,
    )
