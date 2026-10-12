$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

.\scripts\local_pg_env.bat | Out-Null

$env:PHONE_WATCH_DB_BACKEND = "postgres"
$env:PHONE_WATCH_PG_DRIVER = "pg8000"
$env:PHONE_WATCH_PG_HOST = "127.0.0.1"
$env:PHONE_WATCH_PG_DATABASE = "phone_scraper"
$env:PHONE_WATCH_PG_USER = "postgres"
$env:PHONE_WATCH_PG_PASSWORD = "replace_with_local_password"
$env:PHONE_WATCH_PG_PORT = "5432"
$env:PHONE_WATCH_PG_OPTIONS = "-c client_encoding=utf8"
$env:PHONE_WATCH_PG_CONNECT_TIMEOUT = "10"

$env:DINGTALK_TOKEN_URL = "https://oapi.dingtalk.com/gettoken"
$env:DINGTALK_TOKEN_APP_KEY = "replace_with_token_app_key"
$env:DINGTALK_TOKEN_APP_SECRET = "replace_with_token_app_secret"
$env:DINGTALK_AGENT_ID = "replace_with_agent_id"
$env:DINGTALK_PROCESS_CODE = "replace_with_process_code"
$env:DINGTALK_ORIGINATOR_USER_ID = "replace_with_originator_user_id"
$env:DINGTALK_DEPT_ID = "-1"

if (-not (Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

python -u -m phone_watch serve-dingtalk --host 127.0.0.1 --port 5011
