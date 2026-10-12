@echo off
setlocal
cd /d "%~dp0.."

python -m phone_watch export-html --db data\phones.sqlite --out data\phone_watch.html
if errorlevel 1 (
  echo.
  echo HTML export failed.
  pause
  exit /b 1
)

start "" "%cd%\data\phone_watch.html"

