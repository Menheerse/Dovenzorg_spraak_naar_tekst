@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo De app is niet geinstalleerd in deze map. Voer eerst installeren.bat uit.
  pause
  exit /b 1
)
.venv\Scripts\python -m meelezen.psalmen %*
pause
