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

### Pendiente (capa de seguridad y operación)
- `killswitch.py` — panic-close (cerrar todo y detener el bot)
- `notifier.py` — alertas Telegram (y luego email)
- `bot.py` — loop principal que orquesta: data → señal → riesgo → orden →
  estado → journal → alerta
- `evaluator.py` / `proposer.py` — motor de aprendizaje (necesitan datos de
  operación real para tener algo que evaluar)
- CI/CD, observabilidad, deploy en Railway

**Orden recomendado:** primero validar estrategia (paso 4). Si hay edge,
completar killswitch + notifier + bot.py, hacer paper trading en testnet, y
recién después CI/CD y deploy. Si no hay edge, iterar la estrategia primero.

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
