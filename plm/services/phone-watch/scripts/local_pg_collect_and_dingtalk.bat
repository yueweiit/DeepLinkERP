@echo off
setlocal
cd /d "%~dp0.."
call scripts\local_pg_env.bat
if not exist logs mkdir logs

echo ==== %date% %time% local collect start ==== >> logs\daily_collect.log
python -u -m phone_watch collect --max-pages 6 --timeout 20 --retention-months 5 --export-out data\phone_watch.html >> logs\daily_collect.log 2>&1
if errorlevel 1 (
  echo ==== %date% %time% local collect failed ==== >> logs\daily_collect.log
  exit /b 1
)

echo ==== %date% %time% dingtalk sync start ==== >> logs\daily_collect.log
python -u -m phone_watch sync-dingtalk --source-table candidates --latest-date --limit 200 >> logs\daily_collect.log 2>&1
if errorlevel 1 (
  echo ==== %date% %time% dingtalk sync failed ==== >> logs\daily_collect.log
  exit /b 1
)

echo ==== %date% %time% local collect and dingtalk sync done ==== >> logs\daily_collect.log
