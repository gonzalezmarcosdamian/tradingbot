"""
config_versions.py — Versionado de parámetros ajustables.

Columna vertebral del aprendizaje seguro. Separa:

  NÚCLEO NO-AJUSTABLE (CORE_INVARIANTS):
    Constantes que el aprendizaje NUNCA puede tocar. Viven en código, no en la
    DB, para que ni siquiera exista el camino de modificarlas en runtime.
    Cambiarlas es una decisión humana deliberada (editar este archivo + tests).

  AJUSTABLES (ADJUSTABLE_RANGES):
    Parámetros que el aprendizaje puede mover, pero SOLO dentro de rangos duros.
    La validación de rangos es la compuerta: un set fuera de rango se RECHAZA,
    no se guarda. Los rangos son parte del núcleo: el aprendizaje no los elige.

Proceso seguro:
  propose_version() valida → si OK, guarda una versión inmutable y numerada.
  activate() marca cuál está vigente. rollback() vuelve a una anterior.
  Versionado APPEND-ONLY: nunca se borra → el rollback siempre tiene destino.
"""

import os
import json
import sqlite3
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone


# ── NÚCLEO NO-AJUSTABLE ────────────────────────────────────────────
# El aprendizaje no puede alterar nada de esto. Son invariantes de seguridad.
CORE_INVARIANTS = {
    "all_orders_through_risk": True,   # toda orden pasa por risk.py
    "idempotent_orders": True,         # clientOrderId siempre
    "reconcile_on_start": True,        # reconciliación obligatoria al arrancar
    "circuit_breaker_exists": True,    # el breaker no se puede desactivar
    "killswitch_exists": True,         # el kill-switch no se puede desactivar
    "long_only": True,                 # sin shorts
    "no_leverage": True,               # sin apalancamiento
    "max_capital_fraction_hard": 0.95, # techo absoluto, ni el rango lo supera
}


# ── AJUSTABLES Y SUS RANGOS DUROS (la jaula) ──────────────────────
# (min, max) inclusive. El aprendizaje solo puede moverse acá dentro.
ADJUSTABLE_RANGES = {
    "fast_ma": (10, 50),
    "slow_ma": (50, 200),
    "capital_fraction": (0.50, 0.95),
    "stop_loss_pct": (0.01, 0.05),
    "daily_loss_limit": (0.03, 0.08),
    # timeframe es un set discreto, se valida aparte
}
ALLOWED_TIMEFRAMES = {"1h", "4h"}

DEFAULT_PARAMS = {
    "fast_ma": 20,
    "slow_ma": 100,
    "capital_fraction": 0.95,
    "stop_loss_pct": 0.02,
    "daily_loss_limit": 0.05,
    "timeframe": "1h",
}


def data_dir() -> str:
    d = os.getenv("DATA_DIR", "./data")
    os.makedirs(d, exist_ok=True)
    return d


@dataclass
class ParamSet:
    fast_ma: int
    slow_ma: int
    capital_fraction: float
    stop_loss_pct: float
    daily_loss_limit: float
    timeframe: str

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ParamSet":
        return ParamSet(**{k: d[k] for k in DEFAULT_PARAMS})


@dataclass
class ValidationResult:
    valid: bool
    errors: list = field(default_factory=list)


def validate_params(params: dict) -> ValidationResult:
    """Compuerta de seguridad: valida que todo respete los rangos duros.

    Un set inválido NO se guarda. Esto es lo que impide que el aprendizaje
    elija valores peligrosos.
    """
    errors = []

    # Todas las claves esperadas presentes
    for key in DEFAULT_PARAMS:
        if key not in params:
            errors.append(f"falta el parámetro '{key}'")
    if errors:
        return ValidationResult(False, errors)

    # Rangos numéricos
    for key, (lo, hi) in ADJUSTABLE_RANGES.items():
        val = params[key]
        if not (lo <= val <= hi):
            errors.append(f"'{key}'={val} fuera de rango [{lo}, {hi}]")

    # Timeframe discreto
    if params["timeframe"] not in ALLOWED_TIMEFRAMES:
        errors.append(f"timeframe '{params['timeframe']}' no permitido "
                      f"(opciones: {sorted(ALLOWED_TIMEFRAMES)})")

    # Coherencia: fast debe ser estrictamente menor que slow
    if params["fast_ma"] >= params["slow_ma"]:
        errors.append(f"fast_ma ({params['fast_ma']}) debe ser < slow_ma "
                      f"({params['slow_ma']})")

    # Techo absoluto del núcleo: ni el rango puede superar el invariante duro
    hard_cap = CORE_INVARIANTS["max_capital_fraction_hard"]
    if params["capital_fraction"] > hard_cap:
        errors.append(f"capital_fraction supera el techo duro del núcleo {hard_cap}")

    return ValidationResult(len(errors) == 0, errors)


VERSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS config_versions (
    version INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    params_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0
);
"""


class ConfigStore:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.path.join(data_dir(), "config.db")
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(VERSIONS_SCHEMA)
        self.conn.commit()
        # Si no hay ninguna versión, sembrar la default (validada)
        if self._count() == 0:
            self.propose_version(DEFAULT_PARAMS, reason="default inicial", activate=True)

    def _count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM config_versions").fetchone()[0]

    def propose_version(self, params: dict, reason: str, activate: bool = False) -> int:
        """Valida y, si pasa, guarda una versión inmutable. Devuelve el nº de versión.

        Lanza ValueError si los params violan los rangos (no se guarda nada).
        """
        result = validate_params(params)
        if not result.valid:
            raise ValueError("params inválidos: " + "; ".join(result.errors))

        ts = datetime.now(timezone.utc).isoformat()
        # Normalizamos al orden canónico
        clean = ParamSet.from_dict(params).to_dict()
        cur = self.conn.execute(
            "INSERT INTO config_versions (created_at, reason, params_json, active) "
            "VALUES (?, ?, ?, 0)",
            (ts, reason, json.dumps(clean)),
        )
        version = cur.lastrowid
        self.conn.commit()
        if activate:
            self.activate(version)
        return version

    def activate(self, version: int):
        """Marca una versión como la activa (desactiva las demás)."""
        exists = self.conn.execute(
            "SELECT 1 FROM config_versions WHERE version = ?", (version,)
        ).fetchone()
        if not exists:
            raise ValueError(f"la versión {version} no existe")
        self.conn.execute("UPDATE config_versions SET active = 0")
        self.conn.execute(
            "UPDATE config_versions SET active = 1 WHERE version = ?", (version,)
        )
        self.conn.commit()

    def get_active(self) -> ParamSet:
        """Devuelve el ParamSet activo."""
        row = self.conn.execute(
            "SELECT params_json FROM config_versions WHERE active = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("no hay versión activa")
        return ParamSet.from_dict(json.loads(row[0]))

    def get_active_version_number(self) -> int:
        row = self.conn.execute(
            "SELECT version FROM config_versions WHERE active = 1"
        ).fetchone()
        return row[0] if row else -1

    def rollback(self, to_version: int):
        """Vuelve a una versión anterior. El rollback siempre está disponible
        porque el versionado es append-only."""
        self.activate(to_version)

    def history(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT version, created_at, reason, params_json, active "
            "FROM config_versions ORDER BY version DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"version": v, "created_at": c, "reason": r,
             "params": json.loads(p), "active": bool(a)}
            for (v, c, r, p, a) in rows
        ]

    def close(self):
        self.conn.close()
