# NEXT_STEPS — Cómo retomar desde tu PC

Guía para continuar el proyecto en VSCode. Resume dónde estamos, cómo pushear
a tu repo, cómo correr todo, y qué sigue.

Repo destino: https://github.com/gonzalezmarcosdamian/tradingbot

---

## 1. Pushear a tu repo (desde esta carpeta, en tu PC)

El proyecto ya viene con un commit inicial hecho. Solo conectá tu remoto y pushea:

```bash
# Dentro de la carpeta del proyecto
git remote add origin https://github.com/gonzalezmarcosdamian/tradingbot.git
git branch -M main
git push -u origin main
```

Si el repo ya tenía contenido y rechaza el push, traé primero lo remoto:
```bash
git pull origin main --allow-unrelated-histories
# resolvé conflictos si los hay, luego:
git push -u origin main
```

---

## 2. Setup del entorno

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

---

## 3. Correr los tests (deberían pasar 72)

```bash
pytest tests/ -v
```

---

## 4. LO PRIMERO A HACER: validar la estrategia con data real

Esto es el paso pendiente más importante. Necesita acceso a Binance (tu PC lo
tiene; el entorno donde se generó el código, no).

```bash
# Backtest base SMA/EMA con walk-forward
python run_backtest.py

# Comparación: base vs mejoras (filtros de tendencia, régimen, trailing stop)
python run_strategy_comparison.py
```

**Qué mirar en los resultados (números OUT-OF-SAMPLE, no in-sample):**
- ¿Alguna variante supera al Buy & Hold en Sharpe Y mejora el drawdown?
- ¿El filtro de tendencia estabiliza los parámetros? (señal sana)
- Si nada bate al B&H y los drawdowns son enormes → el cruce de medias no es
  viable para BTC, y conviene cambiar de estrategia (no de infraestructura).

En pruebas con datos sintéticos, el cruce —incluso mejorado— no le ganó al
Buy & Hold y tuvo drawdowns inoperables (~-70%). Confirmá si tu data real
muestra el mismo patrón antes de invertir más en el sistema.

---

## 5. Estado del proyecto

### Hecho (con tests)
- `config.py`, `exchange.py` — conexión a Binance (testnet, solo lectura)
- `strategy.py` — señales SMA/EMA crossover
- `backtest.py`, `walkforward.py` — motor de backtest out-of-sample con fees
- `strategy_filters.py` — mejoras componibles (trend, regime, trailing)
- `risk.py` — gestión de riesgo (sizing, stops, circuit breaker) [13 tests]
- `state.py` — persistencia + reconciliación (cuenta dedicada) [13 tests]
- `orders.py` — validación + envío idempotente (market/limit) [15 tests]
- `journal.py` — registro append-only para auditoría/impuestos [7 tests]
- `config_versions.py` — versionado de parámetros, rangos duros, rollback [17 tests]
- `test_strategy_filters.py` [7 tests]
- Docs: ARCHITECTURE.md, CLAUDE.md, LEARNING.md

### Hecho (capa de seguridad — agregado jun-2026)
- `killswitch.py` — panic-close + halt flag persistente [6 tests]
- `notifier.py` — alertas Telegram (degrada con gracia, envío inyectable) [12 tests]
- `bot.py` — loop principal `run_once()`: killswitch → reconciliar → señal →
  riesgo → orden → estado → journal → alerta. Probado entero con fakes [7 tests]

### Pendiente
- **Adaptador CCXT→testnet** para `bot.main()` (etapa 3, paper trading). El
  `run_once()` ya está probado con fakes; falta el cliente real sobre
  testnet.binance.vision (create_order/fetch_order/market_filters/balances).
- `evaluator.py` / `proposer.py` — motor de aprendizaje (necesitan datos de
  operación real para tener algo que evaluar)
- CI/CD, observabilidad, deploy en Railway
- Persistir el `RiskState` (circuit breaker diario) entre reinicios: hoy vive en
  memoria en el loop, un restart lo resetea. OK para paper, no para mainnet.

### ⚠️ Bloqueante real: la estrategia no tiene edge
La validación con data real de Binance (jun-2026) confirmó lo que predecía la
data sintética: el cruce de medias **no le gana al Buy & Hold** en BTC.

| variante | Sharpe OOS | maxDD | vs B&H |
|----------|-----------|-------|--------|
| SMA base | -1.03 | -44% | peor |
| EMA base | -1.75 | -57% | peor |
| mejor variante (SMA+trailing) | -0.95 | -39% | peor |

Buy & Hold del período: -2.4%. **Ninguna variante da Sharpe positivo.** Por el
criterio de ARCHITECTURE.md §8, no se avanza a mainnet.

**Actualización (jun-2026): se probaron 5 familias alternativas** (RSI reversion,
Bollinger, Donchian breakout, Donchian+trend, Momentum) con walk-forward sobre
data real → **ninguna tiene edge** tampoco (Sharpe OOS -1.3 a -2.3, todas peor
que B&H). Detalle completo y caminos a seguir en **`RESEARCH_RESULTS.md`**.

Conclusión: el problema no es la plomería (está completa, 117 tests) sino que no
hay edge accesible con timing de precio puro en BTC 1h en este régimen. Próximo
paso recomendado: **camino 1 de RESEARCH_RESULTS.md** (DCA/rebalanceo, que usa
toda la capa de seguridad y NO requiere edge) o cambiar timeframe/datos.

**Orden recomendado:** la capa de seguridad ya está. El siguiente paso es
iterar la ESTRATEGIA hasta encontrar edge OOS; recién ahí tiene sentido el
adaptador testnet, paper trading, CI/CD y deploy.

---

## 6. Reglas del proyecto (ver CLAUDE.md)

- Mainnet bloqueado por código hasta completar la capa de seguridad.
- Nunca claves en el código: siempre `.env` (ya está en `.gitignore`).
- Toda orden pasa por `risk.py`.
- En Railway: el filesystem es efímero. Montar un Volume y setear la env var
  `DATA_DIR` al mount path, o se pierde journal + estado en cada redeploy.

---

## 7. Notas de despliegue (Railway Hobby)

- Crear un Volume, montarlo (ej. en `/data`), setear `DATA_DIR=/data`.
- Variables de entorno necesarias: `BINANCE_API_KEY`, `BINANCE_API_SECRET`,
  `USE_TESTNET=true`, `DATA_DIR`.
- API key de Binance: permiso de trade SÍ, retiro (withdrawal) NO. IP whitelist.
