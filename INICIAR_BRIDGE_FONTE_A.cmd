@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Instale o ambiente .venv conforme README.md & pause & exit /b 1)
REM Confira se o IP atual da NodeMCU ainda e 192.168.25.171.
".venv\Scripts\python.exe" -m fonte_a_bridge.bridge --source-id FONTE_A --node-ip 192.168.25.171 --advertise-ip 192.168.25.4 --gateway-ip 192.168.25.4
pause
