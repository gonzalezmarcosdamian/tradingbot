# Trading Bot — Crypto (Binance + CCXT)

Bot de trading de crypto construido sobre la API de Binance vía CCXT.
Desarrollo por etapas, validando seguridad en cada paso antes de tocar dinero real.

## ⚠️ Estado actual: ETAPA 1 — Scaffold (solo lectura, testnet)

En esta etapa el bot **no ejecuta órdenes**. Solo se conecta a Binance Testnet,
lee balance y baja velas. Mainnet está bloqueado por código.

## Setup

1. **Crear entorno e instalar dependencias**

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Generar claves de Testnet**

   Andá a https://testnet.binance.vision, logueate con GitHub y generá
   un par de claves API. **No son tus claves de cuenta real.**

3. **Configurar el `.env`**

   ```bash
   cp .env.example .env
   ```

   Editá `.env` y pegá tus claves de testnet. Dejá `USE_TESTNET=true`.

4. **Pedir fondos de prueba**

   En el testnet vas a tener saldo ficticio para probar. Si no aparece,
   buscá el faucet dentro de testnet.binance.vision.

5. **Correr**

   ```bash
   python main.py
   ```

   Deberías ver tu balance de testnet y las últimas 5 velas de BTC/USDT.

## Roadmap

- [x] **Etapa 1** — Scaffold: conexión, balance, OHLCV (testnet, solo lectura)
- [ ] **Etapa 2** — Estrategia + backtest (cruce de medias) sobre data histórica
- [ ] **Etapa 3** — Paper trading en testnet (el bot opera con plata falsa)
- [ ] **Etapa 4** — Capa de seguridad: stop-loss en exchange, reconciliación, kill-switch, alertas
- [ ] **Etapa 5** — Mainnet con capital mínimo, supervisado

## Seguridad

- Claves siempre en `.env` (excluido por `.gitignore`), nunca en el código.
- API key con permiso de **trade** pero **NO de retiro (withdrawal)**.
- Activar **IP whitelist** en Binance.
- Mainnet bloqueado por código hasta completar la etapa 4.
