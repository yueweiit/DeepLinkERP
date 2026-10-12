@echo off
setlocal
cd /d "%~dp0.."

if not exist logs mkdir logs

if "%PHONE_WATCH_DB_BACKEND%"=="" set PHONE_WATCH_DB_BACKEND=postgres
if "%PHONE_WATCH_PG_DRIVER%"=="" set PHONE_WATCH_PG_DRIVER=pg8000
if "%PHONE_WATCH_PG_HOST%"=="" set PHONE_WATCH_PG_HOST=127.0.0.1
if "%PHONE_WATCH_PG_DATABASE%"=="" set PHONE_WATCH_PG_DATABASE=phone_scraper
if "%PHONE_WATCH_PG_USER%"=="" set PHONE_WATCH_PG_USER=postgres
if "%PHONE_WATCH_PG_PORT%"=="" set PHONE_WATCH_PG_PORT=5432
if "%PHONE_WATCH_PG_OPTIONS%"=="" set PHONE_WATCH_PG_OPTIONS=-c client_encoding=utf8
if "%PHONE_WATCH_PG_CONNECT_TIMEOUT%"=="" set PHONE_WATCH_PG_CONNECT_TIMEOUT=10
if "%PHONE_WATCH_PG_PASSWORD%"=="" (
  echo Please set PHONE_WATCH_PG_PASSWORD before running. >> logs\daily_collect.log
  exit /b 1
)

set LOCK_FILE=%TEMP%\phone_watch_daily_collect.lock
if exist "%LOCK_FILE%" (
  echo ==== %date% %time% another collect is running, skip ==== >> logs\daily_collect.log
  exit /b 0
)

echo %date% %time% > "%LOCK_FILE%"

if "%PHONE_WATCH_RETENTION_MONTHS%"=="" set PHONE_WATCH_RETENTION_MONTHS=5
if "%PHONE_WATCH_NEWS_TIMEOUT%"=="" set PHONE_WATCH_NEWS_TIMEOUT=20

echo ==== %date% %time% daily collect start ==== >> logs\daily_collect.log
python -u -m phone_watch collect --max-pages 6 --timeout 20 --retention-months %PHONE_WATCH_RETENTION_MONTHS% --export-out data\phone_watch.html >> logs\daily_collect.log 2>&1
if errorlevel 1 (
  echo ==== %date% %time% daily collect failed ==== >> logs\daily_collect.log
  del "%LOCK_FILE%" >nul 2>nul
  exit /b 1
)
echo ==== %date% %time% daily collect done ==== >> logs\daily_collect.log
echo ==== %date% %time% daily news collect start ==== >> logs\daily_collect.log
python -u -m phone_watch collect-news --timeout %PHONE_WATCH_NEWS_TIMEOUT% >> logs\daily_collect.log 2>&1
if errorlevel 1 (
  echo ==== %date% %time% daily news collect failed, main collect kept ==== >> logs\daily_collect.log
) else (
  echo ==== %date% %time% daily news collect done ==== >> logs\daily_collect.log
)
del "%LOCK_FILE%" >nul 2>nul
