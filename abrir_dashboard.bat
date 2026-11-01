@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERRO: Copie os arquivos .bat para a raiz do projeto, onde fica .venv.
  pause
  exit /b 1
)
start "" "%~dp0iniciar_cliente.bat"
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8080"
