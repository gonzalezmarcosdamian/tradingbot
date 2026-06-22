# Trading Bot — Crypto (Binance + CCXT)

Bot de trading de crypto en Python sobre Binance (vía CCXT), construido por
etapas con **la seguridad y la honestidad de los datos por encima de la
velocidad**. Incluye motor de backtest, capa de seguridad completa, tres modos
de operación y despliegue en la nube.

> ⚠️ **Mainnet bloqueado por código.** Hoy opera solo en **testnet (plata
> falsa)**. Pasar a dinero real es una decisión manual y deliberada — ver
> `MAINNET_CHECKLIST.md`. Esto no es asesoramiento financiero.

---

## Estado actual

- ✅ **Infraestructura completa y probada** — 150 tests.
- ✅ **Research cerrado** (~16 enfoques, backtest sobre data real). Conclusiones:
  - **Trading intradía** (1h/15m, cruces, RSI, breakout, ML, order-flow…) → **sin
    edge**: a esa frecuencia los fees superan cualquier señal débil.
  - **Trend-following DIARIO** (cruce SMA 20/50) → **edge real**: 8 años OOS,
    Sharpe 1.01 vs 0.86 del Buy & Hold, drawdown -54% vs -81%. Generaliza en
    BTC/ETH/BNB/SOL con params fijos (no overfit).
  - **Portfolio multi-activo** (reparto entre los activos en tendencia) → **el
    mejor**: Sharpe 1.14, ~4x el retorno del single-asset.
- ✅ **Modo de trabajo: LOCAL primero.** El bot corre en la PC (paper/testnet).
  Railway está **pausado** (`railway down`) para no consumir; se reactiva cuando
  vayamos a prod. Solo vamos a prod cuando ande bien local.
- ⏳ Pendiente (no es código): tiempo de observación local + decisión de mainnet.

Detalle completo del research en **`PLAN.md`**.

---

## Modos de operación

Un solo entrypoint (`bot.py`), se elige con la env var `MODE`:

| MODE | Qué hace | Estado |
|------|----------|--------|
| `strategy` | Trend-following en UN activo (SMA, configurable) | validado (diario) |
| `dca` | Smart DCA: presupuesto por período repartido por análisis | validado (≈ DCA plano en BTC) |
| `portfolio` | Trend-following multi-activo (reparte entre los que están en tendencia) | ⭐ el mejor |

Parámetros por env (ver `.env.example`): `DEFAULT_TIMEFRAME`, `FAST`, `SLOW`,
`PF_SYMBOLS`, `DCA_*`, `POLL_SECONDS`, `TELEGRAM_*`, `DATA_DIR`.

---

## Arquitectura (módulos)

```
config.py          Config + guard de mainnet
exchange.py        CCXT: ejecución (testnet) + data (mainnet público) separadas
strategy.py        Señales SMA/EMA
signals_research.py  RSI/Bollinger/Donchian/momentum (research)
backtest.py        Motor de backtest con fees + slippage
walkforward.py     Optimización walk-forward (out-of-sample)
risk.py            Sizing, stops, circuit breaker
state.py           Persistencia + reconciliación (cuenta dedicada)
orders.py          Validación + envío idempotente (rechazo vs incierto)
journal.py         Registro append-only (auditoría/impuestos)
killswitch.py      Panic-close + halt flag persistente
notifier.py        Alertas Telegram (degrada con gracia)
evaluator.py       Métricas de paper trading desde el journal
config_versions.py Versionado de parámetros con rangos duros
bot.py             Loop principal (modos strategy/dca/portfolio)
dca.py             Smart DCA
portfolio.py       Bot multi-activo
```

---

## Setup

```bash
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env        # pegá claves de TESTNET (testnet.binance.vision)
```

## Tests

```bash
pytest tests/ -q            # 150 tests
```

## Backtests / research (data real, gratis, local)

```bash
python run_backtest.py              # cruce SMA/EMA walk-forward
python run_research_timeframes.py   # 1h vs 4h vs 1d (clave: el diario gana)
python run_research_daily_validate.py  # SMA diario por año, 8 años
python run_research_robust.py       # robustez: 4 activos, params fijos
python run_research_portfolio.py    # ⭐ portfolio multi-activo
python run_dca_backtest.py          # DCA smart vs plano
```

## Correr el bot (paper / testnet)

```bash
# modo portfolio (recomendado)
MODE=portfolio DEFAULT_TIMEFRAME=1d python bot.py
```

---

## Deploy (Railway, testnet) — actualmente PAUSADO

Enfoque local-first: Railway está **bajado** (`railway down`) para no consumir.
Cuando vayamos a prod se reactiva con `railway up`.

Ver `DEPLOY_RAILWAY.md`. Resumen: proyecto en **región EU** (Binance bloquea IPs
de datacenter US), Volume en `/data` con `DATA_DIR=/data`, variables de entorno
con claves de testnet. Consumo bajo (~$2-4/mes, suele entrar en el crédito Hobby).

- **Pausar:** `railway down -y` (baja el deployment, deja de consumir).
- **Reactivar:** `railway up`.

---

## Seguridad

- Claves siempre en `.env` (gitignored), nunca en el código.
- Mainnet **bloqueado por código** hasta completar `MAINNET_CHECKLIST.md`.
- API key sin permiso de retiro; IP whitelist; toda orden pasa por `risk.py`.
- Kill-switch (`HALT` flag en el volumen) detiene todo y sobrevive reinicios.

## Documentos

- `PLAN.md` — research completo y conclusiones.
- `MAINNET_CHECKLIST.md` — compuerta a dinero real.
- `ARCHITECTURE.md`, `CLAUDE.md`, `LEARNING.md` — diseño y reglas.
