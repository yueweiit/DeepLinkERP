@echo off
cd /d "%~dp0.."
call scripts\local_pg_env.bat
if not exist logs mkdir logs
python -u -m phone_watch serve-dingtalk --host 127.0.0.1 --port 5011 >> logs\dingtalk_connector.log 2>&1
