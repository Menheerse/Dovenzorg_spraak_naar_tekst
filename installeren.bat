@echo off
setlocal
cd /d "%~dp0"
echo === Meelezen installeren ===

rem De spraakherkenning werkt (nog) niet met de nieuwste Python 3.14/3.15.
rem Daarom zoeken we Python 3.12 (of 3.13 / 3.11) en installeren we 3.12 als die er niet is.
set "PY="
for %%v in (3.12 3.13 3.11) do (
  if not defined PY (
    py -%%v -c "pass" >nul 2>nul && set "PY=py -%%v"
  )
)
if not defined PY (
  echo Python 3.12 wordt geinstalleerd ^(naast uw huidige Python^)...
  winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
  py -3.12 -c "pass" >nul 2>nul && set "PY=py -3.12"
)
if not defined PY (
  echo.
  echo Python 3.12 niet gevonden. Installeer het via:
  echo   https://www.python.org/downloads/release/python-31210/
  echo en start daarna dit bestand opnieuw.
  pause
  exit /b 1
)
echo Gebruikt: %PY%

rem Een eerdere, mislukte installatie met een verkeerde Python opruimen
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" || (
    echo Oude installatie met verkeerde Python wordt verwijderd...
    rmdir /s /q .venv
  )
)
if not exist .venv %PY% -m venv .venv

.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt || (echo. & echo Installatie mislukt. Maak een foto van deze melding. & pause & exit /b 1)
where nvidia-smi >nul 2>nul && (
  echo NVIDIA-videokaart gevonden: extra onderdelen installeren...
  .venv\Scripts\python -m pip install -r requirements-nvidia.txt
)

rem Gratis vertalen op de videokaart: Ollama met een vertaalmodel (alleen bij NVIDIA)
where nvidia-smi >nul 2>nul && (
  echo.
  echo Ollama voor gratis vertalen installeren...
  .venv\Scripts\python -m meelezen.ollama installeren
)

where ffmpeg >nul 2>nul || winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
rem Deno is nodig voor YouTube
where deno >nul 2>nul || winget install --id DenoLand.Deno -e --accept-source-agreements --accept-package-agreements

rem Aangeroepen vanuit INSTALLEREN-NIEUWE-COMPUTER.bat: die doet de rest zelf
if defined MEELEZEN_STIL exit /b 0
echo.
.venv\Scripts\python -m meelezen.controle
echo Klaar. Volg het advies hierboven, en start daarna demo.bat of start.bat.
pause
