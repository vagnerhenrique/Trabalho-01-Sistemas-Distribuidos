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
echo Dashboard Web - Trabalho 01
 echo Endereco: http://127.0.0.1:8080
 echo =========================================
".venv\Scripts\python.exe" -m client.gui --host 127.0.0.1 --web-port 8080
echo.
echo Cliente encerrado. Confira as mensagens acima.
pause
