"""
exchange.py — Conexión a Binance vía CCXT.

Dos capas:
  1. Funciones sueltas de lectura (etapa 1): build_exchange, fetch_balance,
     fetch_ohlcv.
  2. `CCXTExchange`: adaptador que implementa las interfaces que consumen
     bot.py (BotExchange), orders.py (ExchangeClient), state.py (reconcile) y
     killswitch.py (PanicExchange) sobre un cliente CCXT real. Es el puente
     entre la lógica probada con fakes y Binance testnet.

Todo el adaptador asume CUENTA DEDICADA al bot (ver state.py): el balance real
del activo base es fuente de verdad de la posición.
"""

import ccxt
from config import Config


def build_exchange(config: Config = Config) -> ccxt.binance:
    """Construye y devuelve un cliente CCXT de Binance.

    Si USE_TESTNET es True, apunta al sandbox de Binance (plata falsa).
    """
    exchange = ccxt.binance(
        {
            "apiKey": config.API_KEY,
            "secret": config.API_SECRET,
            "enableRateLimit": True,  # respeta rate limits automáticamente
            "options": {
                "defaultType": "spot",
                # Sincroniza el reloj local con el del exchange antes de firmar:
                # evita "Timestamp outside recvWindow" cuando el host (ej. un
                # contenedor en la nube) tiene el reloj corrido. Sin esto, la
                # primera llamada firmada (fetch_balance) puede fallar y disparar
                # un halt de reconciliación.
                "adjustForTimeDifference": True,
            },
        }
    )

    if config.USE_TESTNET:
        # Activa el modo sandbox de CCXT → endpoints de testnet
        exchange.set_sandbox_mode(True)

    return exchange


def fetch_balance(exchange: ccxt.binance) -> dict:
    """Devuelve los balances no nulos de la cuenta."""
    balance = exchange.fetch_balance()
    # Filtramos solo los activos con saldo > 0 para que sea legible
    non_zero = {
        asset: amount
        for asset, amount in balance["total"].items()
        if amount and amount > 0
    }
    return non_zero


def fetch_ohlcv(exchange: ccxt.binance, symbol: str, timeframe: str, limit: int = 100):
    """Devuelve velas OHLCV: [timestamp, open, high, low, close, volume]."""
    return exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)


# ── Adaptador para el bot (etapa 3+) ───────────────────────────────

class CCXTExchange:
    """Adaptador delgado sobre un cliente CCXT.

    Traduce la interfaz unificada que esperan los módulos del bot a llamadas
    CCXT concretas. No tiene lógica de negocio: solo mapea y normaliza. La
    lógica sensible ya vive (y se testea) en risk/orders/state/killswitch.

    El cliente se inyecta para poder testear con un fake sin tocar Binance.
    """

    def __init__(self, client, symbol: str = "BTC/USDT"):
        self.client = client
        self.symbol = symbol
        self._markets_loaded = False

    def _ensure_markets(self):
        if not self._markets_loaded:
            self.client.load_markets()
            self._markets_loaded = True

    @staticmethod
    def _base_quote(symbol: str):
        base, quote = symbol.split("/")
        return base, quote

    # ── Lectura de mercado ─────────────────────────────────────────

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list:
        self._ensure_markets()
        return self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def fetch_base_balance(self, symbol: str) -> float:
        """Balance TOTAL del activo base (verdad de la posición en cuenta dedicada)."""
        self._ensure_markets()  # sincroniza la hora (adjustForTimeDifference) antes de firmar
        base, _ = self._base_quote(symbol)
        bal = self.client.fetch_balance()
        return float((bal.get("total", {}) or {}).get(base, 0.0) or 0.0)

    def fetch_quote_balance(self, symbol: str) -> float:
        """Balance LIBRE de quote (USDT disponible para comprar)."""
        self._ensure_markets()
        _, quote = self._base_quote(symbol)
        bal = self.client.fetch_balance()
        return float((bal.get("free", {}) or {}).get(quote, 0.0) or 0.0)

    def market_filters(self, symbol: str) -> dict:
        """Extrae los filtros de Binance (LOT_SIZE, NOTIONAL, PRICE_FILTER) en
        el formato que espera orders.py, más un ref_price para validar el
        notional de órdenes market."""
        self._ensure_markets()
        market = self.client.market(symbol)
        raw = {f.get("filterType"): f for f in market.get("info", {}).get("filters", [])}
        out: dict = {}

        lot = raw.get("LOT_SIZE")
        if lot:
            out["step_size"] = float(lot["stepSize"])
        notional = raw.get("NOTIONAL") or raw.get("MIN_NOTIONAL")
        if notional:
            out["min_notional"] = float(notional.get("minNotional", 0) or 0)
        price = raw.get("PRICE_FILTER")
        if price:
            out["min_price"] = float(price["minPrice"])
            out["max_price"] = float(price["maxPrice"])

        # ref_price: último precio, para chequear notional en market orders.
        try:
            out["ref_price"] = float(self.client.fetch_ticker(symbol)["last"])
        except Exception:
            pass  # sin ref_price, orders.py omite el chequeo de notional en market
        return out

    # ── Órdenes ────────────────────────────────────────────────────

    def create_order(self, symbol, type, side, amount, price=None, params=None) -> dict:
        return self.client.create_order(symbol, type, side, amount, price, params or {})

    def fetch_order(self, client_order_id: str, symbol: str) -> dict:
        """Busca una orden por su clientOrderId (idempotencia/reconciliación).

        En Binance el lookup por client id va en params['origClientOrderId'];
        el id numérico se pasa como None. Si no existe, CCXT levanta excepción
        (lo que orders.py interpreta como 'no existe todavía')."""
        return self.client.fetch_order(None, symbol, {"origClientOrderId": client_order_id})

    def cancel_all_orders(self, symbol: str) -> list:
        return self.client.cancel_all_orders(symbol) or []

    def create_market_sell(self, symbol: str, amount: float) -> dict:
        """Venta a mercado para el panic-close del kill-switch."""
        return self.client.create_order(symbol, "market", "sell", amount)
