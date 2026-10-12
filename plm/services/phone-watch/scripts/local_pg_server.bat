@echo off
setlocal
cd /d "%~dp0.."
call scripts\local_pg_env.bat
if not exist logs mkdir logs
set PHONE_WATCH_PORT=%~1
if "%PHONE_WATCH_PORT%"=="" set PHONE_WATCH_PORT=8000
echo ==== %date% %time% server start port %PHONE_WATCH_PORT% ==== >> logs\server.log
python -u -m phone_watch serve --port %PHONE_WATCH_PORT% >> logs\server.log 2>&1
