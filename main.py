"""
main.py — Prueba del scaffold (ETAPA 1).

Qué hace:
  1. Valida la configuración (claves presentes, testnet forzado).
  2. Se conecta a Binance Testnet.
  3. Lee tu balance de testnet.
  4. Baja las últimas velas de BTC/USDT en 1h.

Qué NO hace:
  - NO ejecuta órdenes. Solo lectura. Cero riesgo.

Uso:
  python main.py
"""

import sys
import pandas as pd

from config import Config
from exchange import build_exchange, fetch_balance, fetch_ohlcv


def main():
    # ── 1. Validar configuración ──────────────────────────────
    try:
        Config.validate()
    except ValueError as e:
        print(f"\n❌ {e}\n")
        sys.exit(1)

    modo = "TESTNET (plata falsa)" if Config.USE_TESTNET else "MAINNET"
    print(f"\n🔌 Conectando a Binance — modo: {modo}")
    print(f"   Par: {Config.SYMBOL} | Timeframe: {Config.TIMEFRAME}\n")

    # ── 2. Conectar ───────────────────────────────────────────
    try:
        exchange = build_exchange()
        exchange.load_markets()
    except Exception as e:
        print(f"❌ Error conectando a Binance: {e}")
        print("   Revisá: claves de testnet correctas, conexión a internet.")
        sys.exit(1)

    # ── 3. Leer balance ───────────────────────────────────────
    print("💰 Balance (testnet):")
    try:
        balance = fetch_balance(exchange)
        if balance:
            for asset, amount in balance.items():
                print(f"   {asset}: {amount}")
        else:
            print("   (sin saldo — pedí fondos de prueba en el faucet de testnet)")
    except Exception as e:
        print(f"   ❌ No se pudo leer el balance: {e}")

    # ── 4. Bajar velas ────────────────────────────────────────
    print(f"\n📊 Últimas velas de {Config.SYMBOL} ({Config.TIMEFRAME}):")
    try:
        candles = fetch_ohlcv(exchange, Config.SYMBOL, Config.TIMEFRAME, limit=5)
        df = pd.DataFrame(
            candles, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        print(df.to_string(index=False))
    except Exception as e:
        print(f"   ❌ No se pudieron bajar las velas: {e}")

    print("\n✅ Scaffold funcionando. Etapa 1 completada.\n")


if __name__ == "__main__":
    main()
