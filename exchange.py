"""
exchange.py — Conexión a Binance vía CCXT.

En etapa 1 solo se usa para LECTURA (balance, OHLCV).
No hay funciones de creación de órdenes todavía: eso llega en etapas
posteriores junto con la gestión de riesgo.
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
