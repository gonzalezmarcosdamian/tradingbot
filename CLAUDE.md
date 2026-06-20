# CLAUDE.md — Guía para Claude Code

Contexto y reglas para trabajar este proyecto con Claude Code. Leer junto con
`ARCHITECTURE.md`, que tiene el diseño completo.

---

## Qué es esto

Bot de trading de crypto (BTC/USDT en Binance, vía CCXT, en Python). Maneja
dinero real en su etapa final, así que **la seguridad y la prudencia priman
sobre la velocidad**.

---

## Reglas de oro (no negociables)

1. **Mainnet bloqueado por código** hasta completar la capa de seguridad
   (etapa 4). No remover ni eludir el guard de `config.py`.
2. **Nunca claves en el código.** Siempre `.env` (ignorado por git).
3. **Toda orden pasa por `risk.py`** antes de enviarse. Sin excepción.
4. **Toda lógica que maneje plata necesita test** antes de considerarse lista.
5. **Validar antes de ejecutar.** Antes de un cambio que toque órdenes,
   estado o riesgo: explicar qué hace, qué puede salir mal, y cómo se revierte.
6. **API key sin permiso de retiro (withdrawal).** Solo trade + lectura.

---

## Estado actual

- ✅ Etapa 1: scaffold (conexión, balance, OHLCV — testnet, solo lectura)
- ✅ Etapa 2: backtest walk-forward SMA/EMA
- ⚠️ Validación con data real (jun-2026): el cruce de medias NO tiene edge en
  BTC. Sharpe OOS negativo en todas las variantes (base y con filtros), peor
  que Buy & Hold. Antes de etapa 3/5 hay que CAMBIAR de estrategia.
- ✅ Etapa 4: capa de seguridad completa con tests (risk, state, orders,
  journal, config_versions, killswitch, notifier, bot). 97 tests en verde.
- ⛔ Etapa 5: mainnet — bloqueado (y sin estrategia con edge, no se habilita)

---

## Convenciones de código

- Python 3.10+, type hints donde aporte claridad.
- Funciones puras y testeables; separar lógica de I/O.
- Comentarios en español, explicando el *por qué* no el *qué*.
- Sin dependencias nuevas sin justificar (evitar bloat).
- Cada módulo de la capa de seguridad: pequeño, con responsabilidad única.

---

## Flujo de trabajo esperado

Antes de cada cambio relevante:
1. Decir qué se va a hacer y por qué.
2. Listar qué puede salir mal y el plan si falla.
3. Validar con tests (sintéticos o testnet, nunca mainnet).
4. Recién entonces, ejecutar.

Preguntar cuando haya ambigüedad en vez de asumir. El usuario es PM, conoce
el ciclo de vida; quiere opciones técnicas accionables y validaciones, no
decisiones tomadas a ciegas.

---

## Comandos útiles

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Etapa 1 — probar conexión (testnet)
python main.py

# Etapa 2 — research de estrategias (data pública)
python run_backtest.py

# Tests (cuando existan)
pytest tests/ -v
```

---

## Anti-objetivos (no construir todavía)

Multi-activo, multi-exchange, machine learning, dashboard web. Son tentadores
pero distraen del objetivo: UN bot confiable operando UN par. Se evalúan
después de que el core funcione en mainnet con capital mínimo.
