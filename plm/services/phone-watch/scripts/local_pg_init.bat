@echo off
setlocal
cd /d "%~dp0.."
call scripts\local_pg_env.bat
python -m phone_watch check-db
if errorlevel 1 exit /b 1
python -m phone_watch init-db
if errorlevel 1 exit /b 1
python -m phone_watch sync-business-tables
