@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-RestMethod http://127.0.0.1:8000/api/summary"

