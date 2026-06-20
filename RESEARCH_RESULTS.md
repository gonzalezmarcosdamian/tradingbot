# RESEARCH RESULTS — Validación de estrategias (jun-2026)

Resultados de backtest **walk-forward out-of-sample** sobre data real de Binance:
BTC/USDT 1h, ~2 años (2024-06-20 → 2026-06-20, 17.520 velas). Costos: 0.1% fee +
0.05% slippage por lado. Optimización solo en train, medición solo en test.

**Benchmark Buy & Hold del período:** ret -1.4% · Sharpe 0.22 · maxDD -52.9%.
(BTC estuvo prácticamente plano con un drawdown enorme: régimen lateral/bajista,
el peor escenario para timing long-only.)

---

## 1. Cruce de medias (estrategia original)

| variante | Sharpe OOS | maxDD | vs B&H |
|----------|-----------|-------|--------|
| SMA base | -1.03 | -44% | peor |
| EMA base | -1.75 | -57% | peor |
| SMA + trend | -2.14 | -58% | peor |
| SMA + regime | -3.75 | -79% | peor |
| SMA + trailing | -0.95 | -39% | peor |
| EMA (todas las variantes con filtros) | -1.8 a -4.2 | -57 a -80% | peor |

## 2. Familias alternativas (research nuevo)

| estrategia | ret OOS | anual | Sharpe | maxDD | exposición |
|------------|---------|-------|--------|-------|-----------|
| RSI reversion | -43.5% | -32.0% | **-1.40** | -46.5% | 23% |
| Bollinger reversion | -51.9% | -39.0% | **-1.69** | -54.6% | 27% |
| Donchian breakout | -41.6% | -30.5% | **-1.44** | -44.6% | 32% |
| Donchian + trend200 | -53.2% | -40.2% | **-2.34** | -53.6% | 27% |
| Momentum (TS) | -44.6% | -32.9% | **-1.32** | -54.5% | 51% |

---

## 3. Veredicto

**Ninguna de las 7 familias probadas le gana al Buy & Hold** (ni en Sharpe ni en
drawdown) out-of-sample. Todas tienen Sharpe OOS netamente negativo. El patrón es
consistente entre enfoques opuestos (reversión a la media *y* seguimiento de
tendencia fallan), lo que apunta a una causa estructural, no a un mal ajuste:

- **El régimen.** BTC fue lateral/bajista con drawdown -53%: castiga a cualquier
  sistema long-only que entra y sale.
- **Los costos.** A 1h, los cambios de posición frecuentes erosionan el retorno
  (0.15% por lado se acumula).
- **No hay edge fácil** en timing puro de precio sobre BTC 1h en este período.

> Esto es un resultado **honesto y útil**: evita quemar capital real persiguiendo
> una señal que el backtest serio dice que no existe. La infraestructura (riesgo,
> estado, órdenes, killswitch, notifier, bot, deploy) está completa y probada
> (117 tests) y es **agnóstica de estrategia**: sirve apenas aparezca un edge real.

---

## 4. Caminos hacia adelante (en orden de relación esfuerzo/realismo)

1. **No hacer timing.** Si el objetivo es exposición a BTC, B&H le gana a todo lo
   probado. El bot puede aportar valor *sin* predecir: **DCA automático**
   (compras programadas) o **rebalanceo** — usos donde la capa de seguridad
   (idempotencia, reconciliación, kill-switch, journal impositivo) es justo lo
   que se necesita y NO requiere edge.
2. **Cambiar el problema, no la plomería:**
   - Otro **timeframe** (diario): menos ruido y menos costos por trade.
   - Otros **datos** (no solo precio): funding rates, basis, on-chain. Ahí puede
     haber señal que el precio puro no tiene.
   - **Market-neutral / pairs**: quita el riesgo direccional que hundió todo acá.
3. **Aceptar que quizá no haya edge accesible** con recursos retail en BTC spot, y
   destinar el sistema a operación disciplinada (camino 1).

**Recomendación:** NO ir a mainnet con ninguna de estas estrategias. Si se quiere
seguir, empezar por el camino 1 (DCA/rebalanceo, alto valor y bajo riesgo) o por
probar timeframe diario + datos no-precio antes de invertir más.

---

## 5. Cómo reproducir

```bash
python run_backtest.py            # cruce SMA/EMA (walk-forward)
python run_strategy_comparison.py # cruce + filtros
python run_research.py            # RSI / Bollinger / Donchian / Momentum
```

Todo usa data pública de Binance (sin claves). Las señales nuevas están en
`signals_research.py`; el walk-forward genérico en `research_wf.py`.
