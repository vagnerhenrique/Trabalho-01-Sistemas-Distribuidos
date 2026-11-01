@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERRO: Copie os arquivos .bat para a raiz do projeto, onde fica .venv.
  pause
  exit /b 1
)
echo Abrindo Gateway, bridge da Fonte A e dashboard...
start "" "%~dp0iniciar_gateway.bat"
timeout /t 2 /nobreak >nul
start "" "%~dp0iniciar_bridge_fonte_a.bat"
start "" "%~dp0iniciar_cliente.bat"
timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:8080"
echo.
echo Componentes iniciados em janelas separadas.
echo Para encerrar, pressione Ctrl+C nas respectivas janelas.
