# run_daily.ps1 — Corrida diaria del bot (UNA iteración) para Task Scheduler.
# Lee el modo del .env (MODE=portfolio). Loguea a logs\daily.log.
# Probar a mano:  powershell -ExecutionPolicy Bypass -File .\run_daily.ps1

Set-Location $PSScriptRoot
$env:RUN_ONCE = "true"
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path "logs")) { New-Item -ItemType Directory "logs" | Out-Null }
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content "logs\daily.log" "`n===== corrida $ts ====="

& ".venv\Scripts\python.exe" bot.py *>> "logs\daily.log"

Add-Content "logs\daily.log" "===== fin (exit $LASTEXITCODE) ====="
