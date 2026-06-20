# LEARNING — Marco de aprendizaje seguro

Cómo el bot aprende de su experiencia y mejora SIN poder romper lo que ya
funciona. El principio: separar lo que puede cambiar de lo que no, y poner un
proceso disciplinado en el medio.

---

## Principio central: separar el "qué" del "cuánto"

- **Núcleo (no ajustable):** la maquinaria que garantiza seguridad y corrección.
  El aprendizaje NUNCA la toca. Cambiarla es una decisión humana deliberada
  (editar código + tests nuevos), jamás una iteración automática.
- **Parámetros (ajustables):** los números con los que opera el bot. Pueden
  moverse según evidencia, pero SOLO dentro de rangos duros definidos de antemano.

Regla de oro: **el aprendizaje solo mueve ajustables, dentro de rangos, y nunca
toca el núcleo.** En el peor caso elige malos parámetros (y el backtest/paper lo
detecta y se revierte), pero no puede desactivar el circuit breaker ni romper la
idempotencia.

---

## Clasificación

### No ajustables (núcleo blindado) — `CORE_INVARIANTS`
- Toda orden pasa por `risk.py` antes de enviarse.
- Idempotencia (clientOrderId) en cada orden.
- Reconciliación obligatoria al arrancar + safe-halt.
- Existencia del circuit breaker, kill-switch y stops (no se pueden desactivar).
- Separación de responsabilidades entre módulos.
- Long-only, sin leverage.
- Techo absoluto de capital (0.95), que ni el rango ajustable puede superar.

### Ajustables (con rangos duros) — `ADJUSTABLE_RANGES`
| Parámetro | Rango duro | Default |
|-----------|-----------|---------|
| `fast_ma` | 10 – 50 | 20 |
| `slow_ma` | 50 – 200 | 100 |
| `capital_fraction` | 0.50 – 0.95 | 0.95 |
| `stop_loss_pct` | 0.01 – 0.05 | 0.02 |
| `daily_loss_limit` | 0.03 – 0.08 | 0.05 |
| `timeframe` | {1h, 4h} | 1h |

Los rangos son parte del núcleo: el aprendizaje no los elige, los respeta.
`validate_params()` es la compuerta: un set fuera de rango se RECHAZA, no se guarda.

---

## Proceso de aprendizaje (6 pasos)

No es "el bot se reprograma solo" — eso rompe sistemas. Es un ciclo con compuertas:

1. **Registrar** — `journal.py` captura cada decisión y resultado. Materia prima.
2. **Evaluar** — periódicamente (no en cada trade): ¿el desempeño real se parece
   al esperado del backtest? ¿Sharpe, drawdown dentro de lo previsto?
3. **Proponer** — sugerir ajustes de parámetros según evidencia, SIEMPRE dentro
   de los rangos (`propose_version()` valida).
4. **Validar** — todo ajuste se prueba primero en backtest/paper, nunca directo
   en vivo. Si no mejora out-of-sample, se descarta.
5. **Promover gradual** — un cambio validado no va al 100% del capital de golpe.
   Monto reducido primero, se observa, escala si confirma.
6. **Revertir** — todo cambio queda versionado (`config_versions.py`, append-only).
   Si un set nuevo rinde peor en vivo, se vuelve al anterior. Rollback siempre
   disponible.

El aprendizaje NUNCA actúa directo sobre dinero real: propone → valida en
simulación → promueve gradual → puede revertir. Cada flecha es una compuerta.

---

## Riesgo principal: overfitting a la experiencia reciente

Si el bot ajusta sus parámetros a las últimas 2 semanas, queda afinado para un
régimen de mercado que quizá ya terminó. Por eso son innegociables:
- Paso 4 (validación out-of-sample).
- Paso 5 (gradualidad).
El sistema debe ser ESCÉPTICO de su propia experiencia reciente.

---

## Autonomía: se gana con historial

- **Fase 1 (ahora) — humano en el loop:** el bot registra, evalúa y propone;
  el humano aprueba cada cambio. Hasta no tener meses de datos en vivo, no hay
  evidencia suficiente para confiar en las propuestas.
- **Fase 2 — semi-automático:** cuando el bot demuestre que sus propuestas
  validadas mejoran las cosas, ajusta dentro de rangos avisando, con veto humano.
- La autonomía aumenta solo cuando el track record la justifica. Empezar
  autónomo sería darle las llaves a quien nunca manejó.

---

## Estado de implementación

- [x] `config_versions.py` — ajustables, rangos duros, núcleo blindado,
      versionado append-only, validación, activación, rollback. (17 tests)
- [ ] `evaluator.py` — desempeño esperado vs real sobre el journal.
- [ ] `proposer.py` — sugiere ajustes dentro de rangos según evaluación.
- [ ] Integración con paper trading para validar propuestas (paso 4).
- [ ] Lógica de promoción gradual (paso 5).
