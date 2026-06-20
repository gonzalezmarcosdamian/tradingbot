# ARCHITECTURE — Trading Bot Crypto (BTC/USDT)

Documento de diseño del proyecto. Define qué construimos, en qué orden, y
qué pasa cuando algo sale mal. Pensado para no perder decisiones entre sesiones.

---

## 1. Objetivo

Bot de trading de crypto que opere **BTC/USDT** en Binance, con ejecución
real, construido por etapas validando seguridad en cada paso antes de tocar
dinero real.

Principio rector: **la estrategia importa menos que todo lo que la rodea.**
Un bot con estrategia mediocre y excelente gestión de riesgo sobrevive; uno
con estrategia brillante y mala gestión de estado se funde con un bug.

---

## 2. Stack

| Componente | Elección | Por qué |
|------------|----------|---------|
| Lenguaje | Python 3.10+ | Ecosistema, ya lo usa el dev |
| Exchange API | CCXT | Abstrae Binance; portable a otros exchanges |
| Exchange | Binance | Liquidez, testnet robusta, websockets estables |
| Data/indicadores | pandas | Estándar |
| Persistencia | SQLite (al inicio) | Suficiente para un bot single-pair |
| Alertas | Telegram | Estándar de facto para bots |
| Config secreta | `.env` (python-dotenv) | Nunca claves en código |

Deliberadamente **fuera de scope** (anti sobre-ingeniería): multi-activo,
multi-exchange, ML, dashboard web. Se suman solo si el core funciona.

---

## 3. Etapas del proyecto

| Etapa | Contenido | Riesgo | Estado |
|-------|-----------|--------|--------|
| 1 | Scaffold: conexión, balance, OHLCV (testnet, solo lectura) | Nulo | ✅ Hecho |
| 2 | Estrategia + backtest walk-forward (SMA/EMA) | Nulo | ✅ Hecho |
| 3 | Paper trading en testnet (bot opera con plata falsa) | Nulo | Pendiente (falta adaptador CCXT→testnet) |
| 4 | **Capa de seguridad** (ver sección 5) | — | ✅ Hecho (97 tests) |
| 5 | Mainnet con capital mínimo, supervisado | Real $ | Bloqueado |

**Regla dura:** mainnet permanece bloqueado por código hasta completar la etapa 4.

> ⚠️ **Validación de estrategia (jun-2026):** el walk-forward sobre data real de
> Binance confirmó que el cruce de medias NO aporta edge en BTC (Sharpe OOS
> negativo en todas las variantes, drawdowns peores que B&H). La capa de
> seguridad está completa, pero por el criterio de la sección 8 NO se avanza a
> etapa 5 hasta tener una estrategia con edge demostrado out-of-sample.

---

## 4. Arquitectura de módulos

```
trading-bot/
├── config.py          # Config + guard de seguridad (testnet/mainnet)
├── exchange.py        # Conexión CCXT a Binance
├── strategy.py        # Señales SMA / EMA crossover
├── backtest.py        # Motor de backtest con fees + slippage
├── walkforward.py     # Optimización out-of-sample
├── run_backtest.py    # Runner de research (etapa 2)
│
│   ── Capa de seguridad (etapa 4) ──
├── risk.py            # Sizing, stops, circuit breaker  ← SIGUIENTE
├── state.py           # Persistencia + reconciliación
├── orders.py          # Validación y envío idempotente de órdenes
├── killswitch.py      # Panic-close + stop del bot
├── notifier.py        # Alertas Telegram
├── journal.py         # Log estructurado de trades (auditoría/impuestos)
│
│   ── Orquestación ──
├── bot.py             # Loop principal: data → señal → riesgo → orden
└── tests/             # Unit + integración contra testnet
```

### Flujo de una decisión (loop principal)

```
1. Bajar última vela cerrada
2. strategy.py  → genera señal (entrar / salir / mantener)
3. risk.py      → ¿permitido? sizing, stops, circuit breaker, exposición
4. orders.py    → valida (min size, step, saldo) y envía con clientOrderId
5. state.py     → persiste el nuevo estado
6. journal.py   → registra la operación
7. notifier.py  → avisa por Telegram
   (en cualquier punto, killswitch.py puede abortar todo)
```

---

## 5. Capa de seguridad (etapa 4) — detalle

### 5.1 Gestión de riesgo (`risk.py`) — CRÍTICO
- **Position sizing**: fracción fija del capital o basado en volatilidad.
- **Stop-loss / take-profit**: por trade. El SL también del lado del exchange.
- **Circuit breaker diario**: si la pérdida del día supera X%, el bot se apaga.
- **Exposición máxima**: tope de capital comprometido.
- Toda orden pasa por validación de riesgo ANTES de enviarse.

### 5.2 Kill-switch (`killswitch.py`) — CRÍTICO
- Comando único que cierra todas las posiciones y detiene el bot.
- Debe funcionar aunque el resto del bot esté colgado.

### 5.3 Persistencia + reconciliación (`state.py`) — CRÍTICO
- Estado en SQLite.
- Al arrancar: consultar estado REAL en el exchange, comparar con lo
  guardado, resolver discrepancias. Nunca confiar solo en memoria.

### 5.4 Journal de trades (`journal.py`) — ALTO
- Cada decisión, orden, fill y error con timestamp.
- Doble propósito: auditoría + registro contable (impuestos AR: Ganancias /
  Bienes Personales requieren el detalle).

### 5.5 Alertas (`notifier.py`) — ALTO
- Telegram en: entrada/salida, stop disparado, circuit breaker, errores.

### 5.6 Validación de órdenes (`orders.py`) — ALTO
- Pre-envío: min notional, step size, precio en límites, saldo suficiente.
- Idempotencia con `clientOrderId` único.

### 5.7 Reconexión robusta — MEDIO
- Reconexión automática de websockets + reconciliación al reconectar.

### 5.8 Tests (`tests/`) — MEDIO
- Unit: lógica de riesgo y señales.
- Integración: contra testnet.

---

## 6. Catálogo de fallas (qué puede salir mal)

| Falla | Mitigación |
|-------|------------|
| Bug en la lógica ejecuta órdenes no deseadas | Testnet primero; validación de riesgo pre-orden |
| Conexión cae a mitad de operación | Idempotencia (clientOrderId) + reconciliación |
| Proceso muere con posición abierta | Stop-loss en el exchange + persistencia de estado |
| Claves API comprometidas | Permiso trade SIN withdrawal; IP whitelist; .env |
| Rate limit / ban | enableRateLimit de CCXT; sin spamear endpoints |
| Slippage / precio malo | Límites de precio; validación de tamaño |
| Racha de pérdidas | Circuit breaker diario apaga el bot |
| Overfitting de la estrategia | Walk-forward out-of-sample; control de estabilidad |
| Pánico del operador | Kill-switch / panic-close |

---

## 7. Decisiones tomadas (registro)

- Par y timeframe por defecto: **BTC/USDT, 1h**.
- Estrategia inicial: **cruce de medias SMA y EMA**, comparadas vs buy-and-hold.
- Validación: **walk-forward** (no backtest in-sample ingenuo).
- Costos asumidos en backtest: **0.1% fee + 0.05% slippage por lado**.
- Modo inicial: **long-only**, sin leverage ni shorts.
- Data de research: **~2 años** (régimen de mercado actual).

---

## 8. Criterio de avance entre etapas

- **Etapa 2 → 3**: solo si el walk-forward muestra edge razonable vs B&H
  (Sharpe OOS competitivo). Si no hay edge, se itera la estrategia. No se
  automatiza algo que el backtest honesto dice que no funciona.
- **Etapa 4 → 5**: solo con TODA la capa de seguridad crítica operativa y
  probada en paper trading. Mainnet arranca con capital mínimo y supervisado.
