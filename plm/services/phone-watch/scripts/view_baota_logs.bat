@echo off
setlocal
cd /d "%~dp0.."

if not exist logs mkdir logs

set LINES=%1
if "%LINES%"=="" set LINES=120

echo.
echo ===== phone-watch logs =====
echo Project: %cd%
echo Lines: %LINES%
echo.

echo ===== daily_collect.log =====
if exist logs\daily_collect.log (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path 'logs\daily_collect.log' -Tail %LINES%"
) else (
  echo logs\daily_collect.log not found
)

echo.
echo ===== server.log =====
if exist logs\server.log (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path 'logs\server.log' -Tail %LINES%"
) else if exist server.log (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path 'server.log' -Tail %LINES%"
) else (
  echo server.log not found
)

echo.
echo ===== recent errors =====
if exist logs\daily_collect.log (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Select-String -Path 'logs\daily_collect.log' -Pattern 'ERROR','WARN','Traceback','failed','Exception','Timeout','429','Lock' | Select-Object -Last 80"
) else (
  echo daily_collect.log not found
)

echo.
echo Done.
