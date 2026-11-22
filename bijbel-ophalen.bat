@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo De app is niet geinstalleerd in deze map:
  echo   %~dp0
  echo Staat dit bestand in de verkeerde map? Het hoort in dezelfde map als start.bat en de map .venv.
  echo Of voer eerst installeren.bat uit in deze map.
  echo.
  pause
  exit /b 1
)
.venv\Scripts\python -m meelezen.bijbel_ophalen
pause
