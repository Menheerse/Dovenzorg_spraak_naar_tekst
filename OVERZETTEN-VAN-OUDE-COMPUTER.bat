@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Meelezen overzetten naar een nieuwe computer
cd /d "%~dp0"

rem Draai dit op de OUDE computer, in de map van Meelezen (bijv. C:\meelezen).
if not exist "config.toml" if not exist "data\bijbel.json" (
  echo.
  echo Dit bestand hoort in de map van Meelezen op de OUDE computer, bijvoorbeeld C:\meelezen.
  echo Kopieer het daarheen en start het opnieuw.
  echo.
  pause
  exit /b 1
)

echo ==========================================================
echo    Meelezen overzetten: gegevens van deze computer inpakken
echo ==========================================================
echo.
set "LIJST="
for %%f in (config.toml data\bijbel.json data\psalmen.json data\formulieren.json data\dienst.json) do (
  if exist "%%f" set "LIJST=!LIJST! %%f" & echo   + %%f
)
for %%f in (data\dienst-*.json) do (
  set "LIJST=!LIJST! data\%%~nxf" & echo   + data\%%~nxf
)

if exist "data\vaste-teksten\" set "LIJST=!LIJST! data\vaste-teksten" & echo   + data\vaste-teksten
if exist "opnames\" (
  for /f "usebackq" %%g in (`powershell -NoProfile -Command "[math]::Round(((Get-ChildItem -LiteralPath 'opnames' -Recurse -File | Measure-Object Length -Sum).Sum)/1MB)"`) do set "MB=%%g"
  echo.
  choice /c JN /m "Ook de opnames meenemen (!MB! MB)"
  if !errorlevel!==1 set "LIJST=!LIJST! opnames" & echo   + opnames
)

if not defined LIJST (
  echo Er is niets om over te zetten.
  pause
  exit /b 1
)

set "BUREAU="
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "BUREAU=%%d"
if not defined BUREAU set "BUREAU=%~dp0"
if "!BUREAU:~-1!"=="\" set "BUREAU=!BUREAU:~0,-1!"
set "UIT=!BUREAU!\meelezen-overzetten.zip"
if exist "%UIT%" del "%UIT%"
echo.
echo Inpakken...
tar -a -c -f "%UIT%" %LIJST%
if errorlevel 1 (
  echo Inpakken is mislukt.
  pause
  exit /b 1
)
echo.
echo Klaar: %UIT%
echo.
echo Zet dit bestand op een USB-stick en kopieer het op de NIEUWE computer
echo naar het bureaublad of naast INSTALLEREN-NIEUWE-COMPUTER.bat.
echo De installatie vindt het dan vanzelf.
echo.
pause
