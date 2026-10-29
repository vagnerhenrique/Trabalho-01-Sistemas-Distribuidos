@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Instale o ambiente .venv conforme README.md & pause & exit /b 1)
start "" "http://127.0.0.1:8080"
".venv\Scripts\python.exe" -m client.gui --host 127.0.0.1 --web-port 8080
pause
