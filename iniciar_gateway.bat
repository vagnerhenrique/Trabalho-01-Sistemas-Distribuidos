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
echo Gateway - Trabalho 01
 echo IP anunciado: 192.168.1.101
 echo UDP: 50001 e 50002 / TCP: 50010
 echo =========================================
".venv\Scripts\python.exe" -m gateway.gateway --advertise-ip 192.168.1.101
echo.
echo Gateway encerrado. Confira as mensagens acima.
pause
