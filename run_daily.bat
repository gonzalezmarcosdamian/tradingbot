@echo off
REM run_daily.bat - Corrida diaria del bot (UNA iteracion) para Task Scheduler.
REM Lee el modo del .env (MODE=portfolio). Loguea a logs\daily.log.
cd /d "%~dp0"
set RUN_ONCE=true
set PYTHONIOENCODING=utf-8
if not exist logs mkdir logs
echo. >> logs\daily.log
echo ===== corrida %date% %time% ===== >> logs\daily.log
".venv\Scripts\python.exe" bot.py >> logs\daily.log 2>&1
REM Refrescar el snapshot de estado (status.json) para visibilidad
".venv\Scripts\python.exe" status.py >> logs\daily.log 2>&1
echo ===== fin (exit %ERRORLEVEL%) ===== >> logs\daily.log
