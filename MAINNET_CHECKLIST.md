# MAINNET CHECKLIST — Camino a dinero real (NO ejecutar sin marcar todo)

Este documento es la **compuerta** entre el paper trading validado y operar con
plata real. Nada de esto se ejecuta solo: cada paso es una decisión humana
deliberada. Mainnet está **bloqueado por código** (`config.py`) hasta que se
complete y se baje el guard a mano.

> Estrategia: trend-following diario SMA 20/50 (validada — ver `PLAN.md` §7-8).
> Estado: corriendo en paper (testnet). Edge real pero con drawdowns grandes
> (es crypto). Esto NO es asesoramiento financiero.

---

## 1. Validación de estrategia — ✅ HECHO
- [x] Edge OOS demostrado (8 años, walk-forward): Sharpe 1.01 vs 0.86 B&H.
- [x] Generaliza entre activos con params fijos (BTC/ETH/BNB/SOL, 4/4).
- [x] Drawdown mejor que B&H (-54% vs -81% en BTC), pero **grande en absoluto**.
- [x] Mejoras evaluadas (trailing stop): no aportan → se mantiene la base.

## 2. Paper trading — período de observación (PENDIENTE)
- [ ] Correr en testnet **al menos un ciclo entrada→salida completo** observado.
- [ ] Verificar en logs: entra cuando el SMA cruza arriba, sale cuando cruza
      abajo, sin errores, sin halts espurios.
- [ ] Confirmar que la reconciliación, el journal y el kill-switch funcionan en
      vivo (ya validados en código + en los incidentes de esta etapa).
- [ ] Recomendado: 2-4 semanas, o hasta ver 1-2 trades reales.

## 3. Seguridad operativa (PENDIENTE antes de plata real)
- [ ] **Cuenta dedicada** al bot (sin holdings personales) — el diseño de
      `state.py`/reconcile lo asume.
- [ ] **API key de MAINNET con permisos mínimos**: Spot trading SÍ,
      **retiro (withdrawal) NO**, margen/futuros NO.
- [ ] **IP whitelist** en Binance. Ojo: Railway no da IP de salida fija en
      Hobby → o se contrata IP estática, o se corre en un host con IP fija, o
      se acepta el riesgo (no recomendado). **Sin withdrawal, el riesgo de una
      key filtrada es acotado** (no pueden sacar fondos).
- [ ] **Rotar** cualquier key que se haya expuesto antes (las de testnet y la
      mainnet/Railway que aparecieron en capturas durante el desarrollo).
- [ ] **Telegram** cableado (`TELEGRAM_BOT_TOKEN`/`CHAT_ID`) para alertas de
      cada entrada/salida/halt — hoy está deshabilitado.
- [ ] Volume de Railway montado y `DATA_DIR` apuntando ahí (journal + estado +
      HALT persisten). Ya configurado.

## 4. Gestión de riesgo (revisar `risk.py` antes de fondear)
- [ ] `capital_fraction` para empezar BAJO (ej. 0.20-0.30, no 0.95).
- [ ] `daily_loss_limit` (circuit breaker) activo y razonable (ej. 0.05).
- [ ] `stop_loss_pct` como red de catástrofe.
- [ ] **Capital mínimo** para arrancar (lo que estés dispuesto a perder).

## 5. Flip a mainnet (el paso técnico, último)
1. En `config.py`: poner `ALLOW_MAINNET = True` y `STAGE` acorde (decisión
   manual, deliberada, commiteada).
2. En Railway: `USE_TESTNET=false`, cargar la API key de **mainnet** (mínimos
   permisos), `DATA_DIR` nuevo y limpio.
3. **El cliente de data sigue siendo mainnet público** (ya lo es) — sin cambios.
4. Deploy. Verificar en logs el arranque y la primera reconciliación contra la
   cuenta real.
5. Observar de cerca los primeros días. Kill-switch a mano disponible (crear el
   archivo `HALT` en el volumen, o `killswitch.panic_close`).

## 6. Criterio GO / NO-GO final
**GO solo si:** estrategia validada (✅) + paper observado sin incidentes (§2) +
seguridad completa (§3) + riesgo conservador (§4) + vos decidís explícitamente
fondear capital que podés perder.

**NO-GO si:** cualquier ítem de §2-4 sin marcar, o dudas. Ante la duda, no.

---

### Recordatorio final
El edge es real pero modesto y cíclico, con drawdowns grandes. Esto puede perder
plata en períodos largos de lateral/bear corto. El DCA sigue siendo la
alternativa más simple y de menor estrés si no querés gestionar un bot direccional.
