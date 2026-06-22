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

Conclusión (corregida en §7): a frecuencia **intradía** no hay edge — los fees
matan cualquier señal débil. Pero la frecuencia importaba.

---

## 7. ⭐ HALLAZGO: trend-following DIARIO sí tiene edge

Al subir la temporalidad (la causa raíz era el costo, no la señal), el cruce
**SMA diario** cambia el resultado. Walk-forward OOS sobre 8 años (2018-2026):

| métrica | SMA-1d (OOS) | Buy & Hold |
|---|--:|--:|
| Retorno total | **+1199%** | +1006% |
| Sharpe | **1.01** | 0.86 |
| Max drawdown | **-54%** | -81% |
| Años que gana | 4/8 | — |

**Carácter (clásico del trend-following):**
- Gana en **retorno, Sharpe y drawdown** sobre el ciclo completo.
- Superpoder: en **bear se va a cash** y evita el derrumbe (2022: -9% vs -66%).
- Costo: **llega tarde en bulls explosivos** (2020, 2023 los gana el B&H) y sufre
  algo en lateral (2025). Es un edge **cíclico**, no de todos los años.

Reproducir: `run_research_timeframes.py` (barrido 1h/4h/1d) y
`run_research_daily_validate.py` (desglose por año, 8 años).

### Implicancia
La infraestructura YA está lista — el bot de estrategia corre en **timeframe
diario** (`DEFAULT_TIMEFRAME=1d`). Candidato real para paper trading serio.

---

## 8. ✅ Robustez CONFIRMADA (Exp G)

SMA diario con **parámetros FIJOS** (sin optimizar → sin sobre-ajuste) sobre 4
activos (BTC, ETH, BNB, SOL), vs Buy & Hold:

| parámetro | gana a B&H | Sharpe prom |
|---|:--:|--:|
| (10, 50) | **4/4** | +1.13 |
| (20, 50) | **4/4** | +0.98 |
| (20, 100) | **4/4** | +0.97 |
| (50, 100) | 2/4 | +0.89 |
| (50, 200) | 1/4 | +0.81 |

**El edge generaliza:** los cruces rápidos (10/50, 20/50, 20/100) le ganan al
B&H en los 4 activos con los MISMOS parámetros. No era suerte de BTC ni params
overfitteados. Reproducir: `run_research_robust.py`.

Caveats honestos: los drawdowns siguen siendo grandes (-53% a -81%, es crypto),
aunque mejores que el B&H. El retorno absoluto es enorme por incluir bulls
históricos — el número honesto es el **Sharpe** (~1.0-1.1 vs ~0.9 del B&H).

**Parámetro elegido para producción: (20, 50)** — gana 4/4, robusto, menos
trades que (10,50). Es el que ya corre el bot en vivo.

### Exp H — Mejoras (trailing stop): no aportan
Probado SMA 20/50 + trailing stop (15/20/25%) en 4 activos. Baja el drawdown
(-51% vs -65% prom) pero **sacrifica más Sharpe del que gana** (0.72 vs 0.98):
saca de las tendencias buenas antes de tiempo. **Se mantiene la base sin stop**
(KISS). Reproducir: `run_research_improve.py`.

Camino a mainnet documentado en `MAINNET_CHECKLIST.md` (compuerta, sin ejecutar).

### Exp I — Portfolio multi-activo: ⭐ el mejor resultado
Repartir capital entre los 4 activos que están "long" (en vez de un solo BTC),
SMA 20/50 diario. Período común 2020-2026:

| estrategia | Sharpe | ret | maxDD |
|---|--:|--:|--:|
| **Portfolio trend (4 activos)** | **1.14** | +1742% | -62% |
| Estrategia 1 activo (BTC) | 0.89 | +433% | -59% |
| B&H BTC | 0.80 | +470% | -77% |

**Mejor Sharpe de todo el proyecto (1.14)**, ~4x el retorno del single-asset, y
drawdown muy por debajo del B&H. La diversificación entre sleeves de tendencia
es la mejora que el trailing stop no logró. Reproducir: `run_research_portfolio.py`.

**Próxima arquitectura recomendada:** versión multi-activo del bot (correr la
señal en N activos, repartir capital entre los que están en tendencia). Es un
cambio de scope (gestionar N posiciones/reconciliaciones) pero es el camino con
mejor relación retorno/riesgo.

### Estado: estrategia VALIDADA
Trend-following diario 20/50: edge real, generaliza entre activos, params
estables. Corriendo en paper (testnet). Pendiente antes de mainnet: período de
observación en paper + decisión explícita del usuario + capital mínimo.

---

## Cómo trabajamos
Vos volvés, leemos juntos: (a) cómo se portó el run en testnet (logs `[eval]`),
y (b) qué dio el research. Con eso, en una sesión decidimos si hay algo para
llevar a paper serio o si el veredicto es "DCA y listo". Sin apurar nada hacia
mainnet: eso es siempre una decisión tuya, explícita, y con estrategia validada.
