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
title Meelezen
rem nieuwe onderdelen uit requirements.txt bijinstalleren (snel als alles er al is)
.venv\Scripts\python -m pip install -q -r requirements.txt >nul 2>nul
rem formulieren eenmalig ophalen (voor het tabblad Formulieren en het rechtzetten van voorgelezen tekst)
if not exist "data\formulieren.json" .venv\Scripts\python -m meelezen.formulieren
rem yt-dlp actueel houden (YouTube verandert vaak)
.venv\Scripts\python -m pip install -U -q "yt-dlp[default]" >nul 2>nul
.venv\Scripts\python -m meelezen.server %*
pause
