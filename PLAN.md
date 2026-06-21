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

### Exp. 2 — Sizing por volatilidad (ATR) — pendiente
### Exp. 3 — Ensamble de señales (voto) — pendiente

> Patrón hasta ahora (7 familias + filtros + MTF): **el timing de precio sobre
> BTC 1h no tiene edge accesible.** Cada experimento que falla refuerza que el
> producto razonable es el **DCA** (acumular), no tradear.

---

## Cómo trabajamos
Vos volvés, leemos juntos: (a) cómo se portó el run en testnet (logs `[eval]`),
y (b) qué dio el research. Con eso, en una sesión decidimos si hay algo para
llevar a paper serio o si el veredicto es "DCA y listo". Sin apurar nada hacia
mainnet: eso es siempre una decisión tuya, explícita, y con estrategia validada.
