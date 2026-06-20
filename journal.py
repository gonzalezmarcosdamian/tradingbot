"""
journal.py — Registro append-only de toda la actividad del bot.

Dos propósitos:
  1. Auditoría: entender POR QUÉ el bot hizo lo que hizo.
  2. Contabilidad: data cruda para impuestos (AR: Ganancias / Bienes Personales).

Diseño:
  - APPEND-ONLY: nunca se edita ni borra. Cambios = eventos nuevos. Historial
    inmutable, requisito de una auditoría seria.
  - DOBLE FORMATO: SQLite (consultable) + log de texto (legible y resistente a
    corrupción de la DB). Redundancia barata.
  - Export a CSV para el contador.

Persistencia en Railway (plan Hobby):
  El filesystem de Railway es EFÍMERO: sin volumen, cada redeploy borra los
  datos. La ruta de datos se lee de la env var DATA_DIR para que en Railway
  apunte al mount del Volume (persistente) y en local a una carpeta normal.
  Setear DATA_DIR al mount path del volumen en el dashboard de Railway.
"""

import os
import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


def data_dir() -> str:
    """Carpeta de datos. En Railway, env var DATA_DIR apunta al Volume."""
    d = os.getenv("DATA_DIR", "./data")
    os.makedirs(d, exist_ok=True)
    return d


class EventType(Enum):
    SIGNAL = "signal"            # decisión de la estrategia
    RISK = "risk"                # aprobado/rechazado por risk.py
    ORDER = "order"              # orden enviada y su resultado
    RECONCILE = "reconcile"      # discrepancias detectadas
    ERROR = "error"              # errores
    HALT = "halt"                # safe-halt
    KILLSWITCH = "killswitch"    # activación del kill-switch
    INFO = "info"                # eventos informativos


JOURNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


@dataclass
class Event:
    ts: str
    type: str
    summary: str
    payload: dict


class Journal:
    def __init__(self, db_path: str | None = None, text_path: str | None = None):
        base = data_dir()
        self.db_path = db_path or os.path.join(base, "journal.db")
        self.text_path = text_path or os.path.join(base, "journal.log")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(JOURNAL_SCHEMA)
        self.conn.commit()

    def log(self, event_type: EventType, summary: str, payload: dict | None = None):
        """Registra un evento. Append-only: solo inserta, nunca modifica."""
        ts = datetime.now(timezone.utc).isoformat()
        payload = payload or {}
        # 1. SQLite
        self.conn.execute(
            "INSERT INTO events (ts, type, summary, payload_json) VALUES (?, ?, ?, ?)",
            (ts, event_type.value, summary, json.dumps(payload, default=str)),
        )
        self.conn.commit()
        # 2. Log de texto (redundancia legible)
        try:
            with open(self.text_path, "a", encoding="utf-8") as f:
                line = f"{ts} [{event_type.value.upper()}] {summary}"
                if payload:
                    line += f" | {json.dumps(payload, default=str)}"
                f.write(line + "\n")
        except OSError:
            # Si falla el texto (ej. permisos), no rompemos: SQLite ya guardó.
            pass

    def query(self, event_type: EventType | None = None, limit: int = 100) -> list[Event]:
        """Consulta eventos, opcionalmente filtrando por tipo."""
        if event_type:
            rows = self.conn.execute(
                "SELECT ts, type, summary, payload_json FROM events "
                "WHERE type = ? ORDER BY id DESC LIMIT ?",
                (event_type.value, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT ts, type, summary, payload_json FROM events "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            Event(ts, t, s, json.loads(p) if p else {})
            for (ts, t, s, p) in rows
        ]

    def export_csv(self, out_path: str, event_type: EventType | None = None) -> str:
        """Exporta eventos a CSV (para el contador / declaración)."""
        if event_type:
            rows = self.conn.execute(
                "SELECT ts, type, summary, payload_json FROM events "
                "WHERE type = ? ORDER BY id ASC",
                (event_type.value,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT ts, type, summary, payload_json FROM events ORDER BY id ASC"
            ).fetchall()
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_utc", "type", "summary", "payload_json"])
            writer.writerows(rows)
        return out_path

    def close(self):
        self.conn.close()
