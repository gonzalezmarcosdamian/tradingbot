# Deploy en Railway — Paper trading en testnet

Guía para correr el bot 24/7 en Railway (plan Hobby), en **modo testnet (plata
falsa)**. Mainnet sigue bloqueado por código: este deploy valida la operación
del sistema, no opera dinero real.

> ⚠️ La estrategia (cruce de medias) **no mostró edge** en el backtest con data
> real. Esto es un ejercicio de infraestructura/paper trading, no un bot
> rentable. Ver `NEXT_STEPS.md`.

---

## 0. Pre-requisitos

1. **Claves de TESTNET** (no mainnet): generalas en
   https://testnet.binance.vision → "Generate HMAC_SHA256 Key".
   Permiso de trade SÍ, retiro NO.
2. Cuenta en https://railway.app (Hobby alcanza).
3. El repo en GitHub (Railway deploya desde ahí) **o** la CLI de Railway.

---

## 1. Archivos que ya vienen listos

| Archivo | Para qué |
|---------|----------|
| `Procfile` | proceso `worker: python -u bot.py` (no es un web service) |
| `railway.json` | builder Nixpacks + start command + restart on-failure |
| `runtime.txt` | fija Python 3.12 |
| `requirements.txt` | dependencias (ccxt, pandas, python-dotenv, requests) |
| `.env.example` | plantilla de todas las variables de entorno |

`bot.py` arranca en `main()`, cablea el adaptador CCXT a **testnet** (gracias a
`set_sandbox_mode`), y corre `run_forever()`: una iteración por vela.

---

## 2. Deploy con la CLI (lo más directo)

```bash
npm i -g @railway/cli      # o: brew install railway
railway login
railway init               # crea el proyecto (o: railway link a uno existente)
railway up                 # sube y deploya el código de esta carpeta
```

## 2-bis. Deploy desde GitHub (alternativa por dashboard)

1. Railway → New Project → Deploy from GitHub repo → elegí `tradingbot`.
2. Railway detecta `railway.json` / `Procfile` y buildea con Nixpacks.

---

## 3. Volume (OBLIGATORIO — si no, perdés journal y estado)

El filesystem de Railway es **efímero**: cada redeploy borra los archivos.

1. En el servicio → **Variables → Volumes → New Volume**.
2. Mount path: `/data`.
3. Seteá la variable `DATA_DIR=/data` (ver abajo).

Sin esto, en cada deploy se pierden `bot.db`, `journal.db`, `journal.log` y —
clave— el **HALT flag** del kill-switch.

---

## 4. Variables de entorno (Service → Variables)

```
BINANCE_API_KEY     = <tu key de TESTNET>
BINANCE_API_SECRET  = <tu secret de TESTNET>
USE_TESTNET         = true
DATA_DIR            = /data
DEFAULT_SYMBOL      = BTC/USDT
DEFAULT_TIMEFRAME   = 1h
STRATEGY            = SMA
FAST                = 20
SLOW                = 50
TELEGRAM_BOT_TOKEN  = <opcional>
TELEGRAM_CHAT_ID    = <opcional>
```

Si `USE_TESTNET` no es `true`, el bot **no arranca** (guard de `config.py`).

---

## 5. Verificar que quedó andando

- **Logs** (Railway → Deployments → Logs): deberías ver
  `bot iniciado (testnet) BTC/USDT 1h ...` y luego, cada hora, una línea de
  iteración (`hold` / `entered` / `exited`).
- Si configuraste Telegram, llega el aviso `🤖 Bot iniciado en testnet`.
- En cada vela, `run_once` decide; las decisiones quedan en el journal (en el
  Volume, consultable).

---

## 6. Kill-switch en producción

El bot se detiene si existe el archivo `HALT` en `DATA_DIR`. Para frenarlo a
mano sin redeploy, podés crear ese archivo (ej. desde un shell de Railway) o
exponer un comando que llame a `killswitch.panic_close(...)`. Mientras el HALT
exista (y el Volume lo persiste), el bot no opera aunque se reinicie.

---

## 7. IP whitelist (importante)

- En **testnet** el whitelist de IP es opcional (no hay plata real).
- Si en el futuro pasás a **mainnet**, NO uses tu IP de casa (es dinámica): hay
  que whitelistear la **IP de egreso estática de Railway** (Settings del
  servicio → Networking). Y recién con una estrategia con edge demostrado.

---

## 8. Checklist antes de marcar "deployado"

- [ ] Claves de **testnet** (no mainnet) cargadas.
- [ ] `USE_TESTNET=true`.
- [ ] Volume montado en `/data` y `DATA_DIR=/data`.
- [ ] Logs muestran iteraciones sin errores de auth.
- [ ] (Opcional) Telegram recibiendo alertas.
