"""
status.py — Snapshot del estado del bot desde los datos locales (sin red).

Lee el journal, el estado y el kill-switch del DATA_DIR y arma un resumen
legible: si está detenido, últimas decisiones, performance de trades cerrados,
errores recientes. Pensado para tener visibilidad rápida (yo lo corro y reporto;
vos no tenés que pegar logs).

Uso:
  python status.py
"""

import json
import os

from dotenv import load_dotenv

load_dotenv()

import killswitch
from journal import Journal, EventType
from evaluator import evaluate, format_report


def _data_dir():
    return os.getenv("DATA_DIR", "./data")


def _short(ts: str) -> str:
    return ts.replace("T", " ")[:19] if ts else "?"


def main():
    print("=" * 60)
    print("ESTADO DEL BOT (datos locales)")
    print("=" * 60)

    # Kill-switch
    if killswitch.is_halted():
        print(f"🚨 HALT ACTIVO: {killswitch.halt_reason()}")
    else:
        print("✅ Operativo (sin halt)")

    j = Journal()

    # Performance de trades cerrados (estrategia)
    print("\n--- Performance (trades cerrados) ---")
    print(format_report(evaluate(j)))

    # Estado de portfolio / dca si existen
    for name, fname in [("DCA", "dca_state.json")]:
        path = os.path.join(_data_dir(), fname)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
            print(f"\n--- {name} ---")
            print(f"  compras: {st.get('total_buys')}  gastado: {st.get('total_spent'):.2f}  "
                  f"BTC: {st.get('smart_total_btc')}")

    # Últimas decisiones
    print("\n--- Últimas 10 acciones ---")
    for e in j.query(limit=10):
        print(f"  {_short(e.ts)}  [{e.type}]  {e.summary}")

    # Errores / halts recientes
    errs = j.query(EventType.ERROR, limit=5) + j.query(EventType.HALT, limit=5)
    if errs:
        print("\n--- ⚠️ Errores / halts recientes ---")
        for e in errs:
            print(f"  {_short(e.ts)}  [{e.type}]  {e.summary}")

    # Última línea del log de texto
    logp = os.path.join(_data_dir(), "journal.log")
    if os.path.exists(logp):
        with open(logp, encoding="utf-8") as f:
            lines = f.read().splitlines()
        if lines:
            print(f"\nÚltimo evento del log: {lines[-1][:100]}")
    print("=" * 60)


if __name__ == "__main__":
    main()
