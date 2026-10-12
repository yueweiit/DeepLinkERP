@echo off
setlocal
cd /d "%~dp0.."

echo Updating phone launch data...
echo This may take a few minutes.
echo.

python -m phone_watch pipeline --db data\phones.sqlite --max-pages 6
if errorlevel 1 (
  echo.
  echo Update failed.
  pause
  exit /b 1
)

python -m phone_watch export-html --db data\phones.sqlite --out data\phone_watch.html
if errorlevel 1 (
  echo.
  echo HTML export failed.
  pause
  exit /b 1
)

echo.
echo Done. Static page:
echo %cd%\data\phone_watch.html
pause

