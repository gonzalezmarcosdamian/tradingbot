"""
config.py — Carga y valida la configuración del bot.

En la ETAPA 1 (scaffold) hay un guard de seguridad que FUERZA testnet.
Mainnet está deliberadamente bloqueado hasta que tengamos las capas de
seguridad (stop-loss en exchange, reconciliación, kill-switch) implementadas.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    API_KEY = os.getenv("BINANCE_API_KEY", "")
    API_SECRET = os.getenv("BINANCE_API_SECRET", "")
    USE_TESTNET = os.getenv("USE_TESTNET", "true").lower() == "true"
    SYMBOL = os.getenv("DEFAULT_SYMBOL", "BTC/USDT")
    TIMEFRAME = os.getenv("DEFAULT_TIMEFRAME", "1h")

    # ── Guard de seguridad de la etapa 1 ──────────────────────
    # Mientras no exista la capa de seguridad, no se permite mainnet.
    STAGE = 1
    ALLOW_MAINNET = False

    @classmethod
    def validate(cls):
        errors = []

        if not cls.API_KEY or cls.API_KEY.startswith("tu_api_key"):
            errors.append(
                "BINANCE_API_KEY no configurada. Copiá .env.example a .env "
                "y poné tus claves de TESTNET."
            )
        if not cls.API_SECRET or cls.API_SECRET.startswith("tu_api_secret"):
            errors.append(
                "BINANCE_API_SECRET no configurada. Copiá .env.example a .env "
                "y poné tus claves de TESTNET."
            )

        # Bloqueo duro de mainnet en esta etapa
        if not cls.USE_TESTNET and not cls.ALLOW_MAINNET:
            errors.append(
                "MAINNET BLOQUEADO en etapa 1. Poné USE_TESTNET=true en .env. "
                "Mainnet se habilita recién cuando esté la capa de seguridad."
            )

        if errors:
            raise ValueError(
                "Errores de configuración:\n  - " + "\n  - ".join(errors)
            )

        return cls
