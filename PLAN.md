# PLAN — Trading en testnet + evaluación (ventana de 3 días)

Objetivo: dejar el bot **operando en testnet** unos días, juntar datos de
operación reales, y volver con una evaluación que diga si la lógica funciona y
qué iterar. Mainnet sigue bloqueado por código — esto es paper trading.

> ⚠️ Recordatorio: el cruce de medias **no mostró edge** en backtest. Este run
> NO busca demostrar rentabilidad (no la tiene), sino **validar la operación en
> vivo** (que ejecute trades, reconcilie, registre, sobreviva días/reinicios) y
> juntar un log de trades real para afinar la evaluación. La mejora del
> algoritmo viene del **track de research** (abajo), no de esperar 3 días.

---

## 1. Qué queda corriendo (Railway, testnet, sin atención)

- **Bot de estrategia** (`MODE=strategy`) operando BTC/USDT en **15m** (más
  cruces → más actividad para observar en pocos días).
- En cada vela: data → señal → riesgo → orden → estado → journal → alerta.
- **Auto-reporte a los logs**: cada ~12 iteraciones imprime una línea `[eval]`
  con trades, win rate y PnL realizado — así ves el progreso **sin entrar al
  volumen** (que está SSH-gated).
- Todo se persiste en el Volume (`/data/trade`): journal (auditoría/impuestos),
  estado, y el flag de kill-switch.

Caveat: la cuenta de testnet viene **sembrada** con 1 BTC + 10.000 USDT, así que
las magnitudes de PnL son ilustrativas (no es una cuenta limpia). Lo que importa
acá es que **los trades se ejecutan y se registran bien**.

---

## 2. Cómo chequear el progreso (vos, en cualquier momento)

En una terminal:
```
railway logs            # log en vivo
railway logs --lines 50 # últimas 50 líneas
```
Buscá:
- `[iter N] entered/exited/hold` → cada decisión.
- `[eval] trades=… winrate=… pnl_realizado=…` → resumen de performance.

O en el dashboard: Railway → **tradingbot** → **Deployments → Logs**.

---

## 3. Track de research (lo avanzo yo entre medio)

Acá es donde puede aparecer edge. Experimentos a backtestear (walk-forward, data
real, sin look-ahead), en orden:
1. **Confirmación multi-timeframe**: operar la señal de 1h solo si el 4h
   acompaña (filtro de tendencia mayor real).
2. **Sizing por volatilidad**: posición inversa a la volatilidad (ATR) en vez de
   fracción fija — suele mejorar el drawdown.
3. **Ensamble de señales**: combinar cruce + momentum + reversión por voto, en
   vez de una sola.
4. **Robustez**: correr cada candidato en varios períodos/activos y ver si el
   resultado se sostiene (no overfitting).

Criterio de éxito (de ARCHITECTURE.md §8): Sharpe OOS competitivo con B&H **y**
mejor drawdown, estable entre ventanas. Si nada lo logra, la conclusión honesta
sigue siendo: para BTC, **acumular (DCA) > tradear**.

---

## 4. Cuando vuelvas (en ~3 días) — pasos

1. **Mirá la performance del run**:
   `railway logs --lines 100` → última línea `[eval]`. O corré el evaluador
   contra los datos: `python evaluator.py` (si tenés el volumen montado/local).
2. **Revisá mis hallazgos de research**: voy a dejar los resultados de los
   experimentos acá mismo (sección 5, abajo) y en commits.
3. **Decidimos la siguiente iteración** según los datos:
   - Si algún experimento mostró edge OOS → lo integramos y lo ponemos en paper.
   - Si no → consolidamos el DCA (que ya funciona) como el producto, y dejamos
     el trading como research.

---

## 5. Resultados de research

### Exp. 1 — Confirmación multi-timeframe (cruce 1h + tendencia 4h) — ❌
Walk-forward OOS, BTC/USDT 2 años (B&H Sharpe 0.23):

| variante | ret OOS | Sharpe | maxDD |
|---|--:|--:|--:|
| cruce 1h (base) | -39.5% | -0.96 | -47.3% |
| 1h + tendencia 4h | -58.1% | **-2.17** | -62.2% |

**Veredicto:** el filtro 4h **empeora** (más negativo, peor drawdown). Filtrar
por el marco mayor no rescata el cruce — coincide con que el `trend_filter` de 1h
ya había empeorado las cosas. Reproducir: `python run_research_mtf.py`.

### Exp. 2 — Sizing por volatilidad (ATR) — descartado
El sizing solo ESCALA una señal; no crea edge. Sobre señales de Sharpe negativo
solo cambia la magnitud de la pérdida, no el signo. No vale correrlo.

### Exp. 3 — Ensamble de señales por voto — ❌
Backtest 2 años (B&H Sharpe 0.23). Mejor variante: mayoría (≥2 de 3).

| variante | ret | Sharpe | maxDD |
|---|--:|--:|--:|
| SMA(20,50) | -41% | -0.70 | -60% |
| Donchian(20,10) | -52% | -1.20 | -65% |
| Momentum(168) | -64% | -1.50 | -68% |
| Ensamble mayoría ≥2 | -47% | **-0.94** | -67% |

**Veredicto:** combinar señales malas da una señal mala. Ningún ensamble supera
al B&H. Reproducir: `python run_research_ensemble.py`.

> **Patrón (10+ negativos): el timing de precio puro sobre BTC 1h no tiene edge
> accesible.** Las variantes simples (cruces, filtros, MTF, ensamble) están
> agotadas.

### Barrido exhaustivo de enfoques NUEVOS (A–D)

| Exp | Enfoque | Mejor Sharpe OOS | vs B&H | Reproducir |
|---|---|--:|---|---|
| A | Volatility breakout (Keltner+ATR, ±volfilt) | -0.96 | ❌ | `run_research_breakout.py` |
| B | Mean-reversion intradía 15m (Bollinger/RSI) | -1.54 | ❌ (fees) | `run_research_intraday.py` |
| C | Market-neutral par BTC/ETH (z-score spread) | -1.00 | ❌ | `run_research_pairs.py` |
| D | No-precio: funding rate (carry/contrarian) | +0.04 | ❌ | `run_research_funding.py` |
| E | ML + order-flow (logistic/gboost, walk-forward) | -8.8 | ❌❌ | `run_research_ml.py` |

**Detalle D (lo único no-terrible):** el *contrarian* de funding (long cuando el
funding es extremadamente negativo) da Sharpe ~0 pero con **drawdown -32% vs
-52% del B&H** y solo 28% de exposición. No es edge (no le gana al B&H en
Sharpe), pero sugiere que el funding extremo aporta info de RIESGO (evita los
peores tramos). Útil como overlay risk-off, no como generador de alpha.

---

## 6. VEREDICTO FINAL (research cerrado)

Se probaron **~15 enfoques** exhaustivamente con backtest honesto sobre data
real: cruces SMA/EMA, filtros (trend/regime/trailing), RSI, Bollinger, Donchian,
momentum, multi-timeframe, ensamble, volatility breakout, mean-reversion
intradía, market-neutral de pares, funding rate y **ML con order-flow
(microestructura)**. **Ninguno supera al Buy & Hold en Sharpe ajustado por riesgo.**

El ML fue el peor (-99%): predecir la vela de 1h es ruido, el modelo sobre-opera
y los fees (0.15%/lado) liquidan la cuenta. Confirma la causa raíz de TODO:
**a esta frecuencia, los costos de transacción superan cualquier señal débil.**

Conclusión honesta: **no hay alpha accesible para este setup retail sobre BTC.**
Lo que SÍ sirve y está validado:
- **DCA** (acumular) — el producto razonable, no requiere edge.
- **Funding contrarian como overlay risk-off** — opcional, reduce drawdown.

Trading por alpha: la evidencia dice que no. No se lleva a mainnet.

---

## Cómo trabajamos
Vos volvés, leemos juntos: (a) cómo se portó el run en testnet (logs `[eval]`),
y (b) qué dio el research. Con eso, en una sesión decidimos si hay algo para
llevar a paper serio o si el veredicto es "DCA y listo". Sin apurar nada hacia
mainnet: eso es siempre una decisión tuya, explícita, y con estrategia validada.
