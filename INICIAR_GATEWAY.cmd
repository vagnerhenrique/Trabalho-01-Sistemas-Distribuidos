@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Instale o ambiente .venv conforme README.md & pause & exit /b 1)
".venv\Scripts\python.exe" -m gateway.gateway --advertise-ip 192.168.1.101
pause
