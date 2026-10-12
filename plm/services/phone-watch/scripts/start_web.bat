@echo off
setlocal
cd /d "%~dp0.."

echo Starting Phone Watch web app...
echo.
echo Keep this window open while using the page.
echo Browser URL: http://127.0.0.1:8000
echo.

if "%PHONE_WATCH_DB_BACKEND%"=="" set PHONE_WATCH_DB_BACKEND=postgres
if "%PHONE_WATCH_PG_DRIVER%"=="" set PHONE_WATCH_PG_DRIVER=pg8000
if "%PHONE_WATCH_PG_HOST%"=="" set PHONE_WATCH_PG_HOST=127.0.0.1
if "%PHONE_WATCH_PG_DATABASE%"=="" set PHONE_WATCH_PG_DATABASE=phone_scraper
if "%PHONE_WATCH_PG_USER%"=="" set PHONE_WATCH_PG_USER=postgres
if "%PHONE_WATCH_PG_PORT%"=="" set PHONE_WATCH_PG_PORT=5432
if "%PHONE_WATCH_PG_OPTIONS%"=="" set PHONE_WATCH_PG_OPTIONS=-c client_encoding=utf8
if "%PHONE_WATCH_PG_CONNECT_TIMEOUT%"=="" set PHONE_WATCH_PG_CONNECT_TIMEOUT=10
if "%PHONE_WATCH_PG_PASSWORD%"=="" (
  echo Please set PHONE_WATCH_PG_PASSWORD before running.
  exit /b 1
)

py -m phone_watch serve --port 8000

echo.
echo Server stopped.
pause
