"""
test_journal.py — Tests del registro append-only.
"""

import os
import csv
import tempfile
import pytest

from journal import Journal, EventType


def make_journal(tmp):
    db = os.path.join(tmp, "j.db")
    txt = os.path.join(tmp, "j.log")
    return Journal(db_path=db, text_path=txt)


def test_log_persiste_en_sqlite():
    with tempfile.TemporaryDirectory() as tmp:
        j = make_journal(tmp)
        j.log(EventType.ORDER, "compra ejecutada", {"qty": 0.01, "price": 50000})
        events = j.query(EventType.ORDER)
        assert len(events) == 1
        assert events[0].summary == "compra ejecutada"
        assert events[0].payload["qty"] == 0.01
        j.close()


def test_log_escribe_texto_legible():
    with tempfile.TemporaryDirectory() as tmp:
        txt = os.path.join(tmp, "j.log")
        j = Journal(db_path=os.path.join(tmp, "j.db"), text_path=txt)
        j.log(EventType.SIGNAL, "EMA cruzó arriba", {"fast": 20, "slow": 100})
        j.close()
        with open(txt, encoding="utf-8") as f:
            content = f.read()
        assert "EMA cruzó arriba" in content
        assert "SIGNAL" in content


def test_append_only_acumula():
    with tempfile.TemporaryDirectory() as tmp:
        j = make_journal(tmp)
        for i in range(5):
            j.log(EventType.INFO, f"evento {i}")
        events = j.query()
        assert len(events) == 5
        j.close()


def test_query_filtra_por_tipo():
    with tempfile.TemporaryDirectory() as tmp:
        j = make_journal(tmp)
        j.log(EventType.ORDER, "orden 1")
        j.log(EventType.ERROR, "error 1")
        j.log(EventType.ORDER, "orden 2")
        orders = j.query(EventType.ORDER)
        errors = j.query(EventType.ERROR)
        assert len(orders) == 2
        assert len(errors) == 1
        j.close()


def test_persiste_entre_instancias():
    # Simula redeploy: cerrar y reabrir desde el mismo archivo
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "j.db")
        txt = os.path.join(tmp, "j.log")
        j1 = Journal(db_path=db, text_path=txt)
        j1.log(EventType.ORDER, "antes del redeploy")
        j1.close()

        j2 = Journal(db_path=db, text_path=txt)
        events = j2.query(EventType.ORDER)
        assert len(events) == 1
        assert events[0].summary == "antes del redeploy"
        j2.close()


def test_export_csv():
    with tempfile.TemporaryDirectory() as tmp:
        j = make_journal(tmp)
        j.log(EventType.ORDER, "compra", {"qty": 0.01})
        j.log(EventType.ORDER, "venta", {"qty": 0.01})
        out = os.path.join(tmp, "export.csv")
        j.export_csv(out, EventType.ORDER)
        with open(out, encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["timestamp_utc", "type", "summary", "payload_json"]
        assert len(rows) == 3  # header + 2 órdenes
        j.close()


def test_fallo_de_texto_no_rompe_sqlite():
    # Si el log de texto no se puede escribir, SQLite igual debe guardar
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "j.db")
        # Ruta de texto inválida (directorio inexistente y no creable como archivo)
        bad_txt = os.path.join(tmp, "no_existe", "sub", "j.log")
        j = Journal(db_path=db, text_path=bad_txt)
        j.log(EventType.INFO, "debe sobrevivir en sqlite")
        events = j.query(EventType.INFO)
        assert len(events) == 1  # SQLite guardó aunque el texto falló
        j.close()
