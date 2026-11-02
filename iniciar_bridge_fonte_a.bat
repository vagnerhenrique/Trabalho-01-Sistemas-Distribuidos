@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERRO: Python da .venv nao foi encontrado nesta pasta.
  echo Copie este arquivo para a raiz do projeto, onde existe a pasta .venv.
  pause
  exit /b 1
)
echo =========================================
echo Bridge gRPC - Fonte A
 echo Gateway/PC: 192.168.1.101
 echo NodeMCU Fonte A: 192.168.1.150
 echo =========================================
".venv\Scripts\python.exe" -m fonte_a_bridge.bridge --source-id FONTE_A --node-ip 192.168.1.150 --advertise-ip 192.168.1.101 --gateway-ip 192.168.1.101
echo.
echo Bridge encerrado. Confira as mensagens acima.
pause
