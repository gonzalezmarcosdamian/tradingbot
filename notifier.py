"""
notifier.py — Alertas por Telegram.

Propósito (ALTO, ver ARCHITECTURE.md 5.5):
  Avisar al operador en los momentos que importan: entrada/salida, stop
  disparado, circuit breaker, halt/kill-switch y errores. Telegram es el
  estándar de facto para bots y no requiere infra propia.

Principios de diseño:
  - DEGRADAR CON GRACIA: si no hay token/chat configurados, el notifier queda
    deshabilitado y los métodos son no-ops que devuelven False. NUNCA debe
    romper el loop de trading por un problema de notificación.
  - TESTEABLE: el envío real se inyecta como un `sender` (callable). Los tests
    pasan un sender falso y verifican el texto, sin tocar la red ni Telegram.
  - El formateo de mensajes es lógica pura (funciones `format_*`) y se testea
    aparte del envío.

Config por entorno:
  TELEGRAM_BOT_TOKEN  — token del bot (de @BotFather)
  TELEGRAM_CHAT_ID    — chat/grupo destino de las alertas
"""

import os
from typing import Callable, Optional


# Un sender recibe (token, chat_id, text) y devuelve True si se envió OK.
Sender = Callable[[str, str, str], bool]


# ── Formateo de mensajes (lógica pura, testeable sin red) ──────────

def format_entry(symbol: str, amount: float, price: float, stop: Optional[float]) -> str:
    msg = f"🟢 ENTRADA {symbol}\nCantidad: {amount:g}\nPrecio: {price:,.2f}"
    if stop is not None:
        msg += f"\nStop-loss: {stop:,.2f}"
    return msg


def format_exit(symbol: str, amount: float, price: float, pnl: Optional[float]) -> str:
    msg = f"🔴 SALIDA {symbol}\nCantidad: {amount:g}\nPrecio: {price:,.2f}"
    if pnl is not None:
        signo = "+" if pnl >= 0 else ""
        msg += f"\nPnL: {signo}{pnl:,.2f}"
    return msg


def format_stop(symbol: str, price: float) -> str:
    return f"🛑 STOP-LOSS disparado en {symbol} @ {price:,.2f}"


def format_circuit_breaker(loss_pct: float) -> str:
    return (f"⚠️ CIRCUIT BREAKER: pérdida diaria {loss_pct:.1%}. "
            f"No se abren nuevas posiciones hoy.")


def format_halt(reason: str) -> str:
    return f"🚨 BOT DETENIDO (halt)\nMotivo: {reason}"


def format_error(context: str, detail: str) -> str:
    return f"❗ ERROR en {context}\n{detail}"


# ── Envío real (se inyecta para poder testear sin red) ─────────────

def _telegram_sender(token: str, chat_id: str, text: str) -> bool:
    """Sender por defecto: pega a la API de Telegram con requests.

    Importa requests adentro para no pagar el import si el notifier está
    deshabilitado o se usa un sender inyectado en tests.
    """
    import requests

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    return resp.ok


class Notifier:
    """Fachada de alertas. Si no está configurado, todos los envíos son no-op."""

    def __init__(
        self,
        token: str = "",
        chat_id: str = "",
        sender: Optional[Sender] = None,
    ):
        self.token = token
        self.chat_id = chat_id
        self._sender = sender or _telegram_sender

    @classmethod
    def from_env(cls, sender: Optional[Sender] = None) -> "Notifier":
        """Construye desde variables de entorno. Si faltan, queda deshabilitado."""
        return cls(
            token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            sender=sender,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.token) and bool(self.chat_id)

    def send(self, text: str) -> bool:
        """Envía un texto. Devuelve True si se envió; False si está
        deshabilitado o si el envío falló. NUNCA propaga la excepción: una
        alerta caída no puede tumbar el bot."""
        if not self.enabled:
            return False
        try:
            return bool(self._sender(self.token, self.chat_id, text))
        except Exception:
            # Silencioso a propósito: el journal ya registra el evento real;
            # acá solo falló el canal de aviso, no la operación.
            return False

    # ── Atajos semánticos para los eventos del bot ─────────────────

    def entry(self, symbol, amount, price, stop=None) -> bool:
        return self.send(format_entry(symbol, amount, price, stop))

    def exit(self, symbol, amount, price, pnl=None) -> bool:
        return self.send(format_exit(symbol, amount, price, pnl))

    def stop(self, symbol, price) -> bool:
        return self.send(format_stop(symbol, price))

    def circuit_breaker(self, loss_pct) -> bool:
        return self.send(format_circuit_breaker(loss_pct))

    def halt(self, reason) -> bool:
        return self.send(format_halt(reason))

    def error(self, context, detail) -> bool:
        return self.send(format_error(context, detail))
