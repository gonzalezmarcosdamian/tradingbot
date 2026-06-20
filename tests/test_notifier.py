"""
test_notifier.py — Tests del notifier de Telegram.

Foco: que degrade con gracia sin config, que no propague excepciones del envío,
y que el formateo de mensajes sea correcto. El envío real se inyecta como fake.
"""

from notifier import (
    Notifier,
    format_entry,
    format_exit,
    format_circuit_breaker,
    format_halt,
)


class FakeSender:
    """Captura los envíos para inspeccionarlos; configurable para fallar."""
    def __init__(self, ok=True, raises=False):
        self.ok = ok
        self.raises = raises
        self.sent = []

    def __call__(self, token, chat_id, text):
        if self.raises:
            raise ConnectionError("telegram caído")
        self.sent.append((token, chat_id, text))
        return self.ok


# ── Habilitación / degradación ─────────────────────────────────────

def test_deshabilitado_sin_config_es_noop():
    sender = FakeSender()
    n = Notifier(token="", chat_id="", sender=sender)
    assert n.enabled is False
    assert n.send("hola") is False
    assert sender.sent == []  # no se intentó enviar nada


def test_habilitado_con_config_envia():
    sender = FakeSender()
    n = Notifier(token="T", chat_id="C", sender=sender)
    assert n.enabled is True
    assert n.send("hola") is True
    assert sender.sent == [("T", "C", "hola")]


def test_envio_que_falla_no_propaga():
    # Una alerta caída NO puede tumbar el bot: devuelve False, no excepción.
    n = Notifier(token="T", chat_id="C", sender=FakeSender(raises=True))
    assert n.send("hola") is False


def test_sender_devuelve_false_si_no_ok():
    n = Notifier(token="T", chat_id="C", sender=FakeSender(ok=False))
    assert n.send("hola") is False


def test_from_env_sin_vars_deshabilitado(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert Notifier.from_env().enabled is False


# ── Atajos semánticos ──────────────────────────────────────────────

def test_atajo_entry_envia_texto_formateado():
    sender = FakeSender()
    n = Notifier(token="T", chat_id="C", sender=sender)
    n.entry("BTC/USDT", 0.01, 50000.0, stop=49000.0)
    assert "ENTRADA" in sender.sent[0][2]
    assert "BTC/USDT" in sender.sent[0][2]


# ── Formateo (lógica pura) ─────────────────────────────────────────

def test_format_entry_incluye_stop():
    msg = format_entry("BTC/USDT", 0.01, 50000.0, 49000.0)
    assert "49,000" in msg and "ENTRADA" in msg


def test_format_entry_sin_stop_no_lo_muestra():
    assert "Stop" not in format_entry("BTC/USDT", 0.01, 50000.0, None)


def test_format_exit_muestra_pnl_con_signo():
    assert "+100" in format_exit("BTC/USDT", 0.01, 51000.0, 100.0)
    assert "-50" in format_exit("BTC/USDT", 0.01, 49000.0, -50.0)


def test_format_circuit_breaker_y_halt():
    assert "CIRCUIT BREAKER" in format_circuit_breaker(0.05)
    assert "DETENIDO" in format_halt("motivo x")
