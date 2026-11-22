@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Meelezen installeren op deze computer
cd /d "%~dp0"
set "BRON=%~dp0"
if "%BRON:~-1%"=="\" set "BRON=%BRON:~0,-1%"

if not exist "%BRON%\meelezen\server.py" (
  echo.
  echo Pak eerst de hele zip uit: rechtermuisknop op de zip, "Alles uitpakken".
  echo Start daarna dit bestand opnieuw vanuit de uitgepakte map.
  echo.
  pause
  exit /b 1
)

echo ==========================================================
echo    Meelezen installeren op deze computer
echo ==========================================================
echo.
echo Dit installeert alles wat nodig is: Python, ffmpeg, de app,
echo de Bijbel, het psalmboek, de formulieren, Matthew Henry en het spraakmodel,
echo en bij een NVIDIA-videokaart ook Ollama voor gratis vertalen.
echo Heeft deze computer een NVIDIA-videokaart ^(zoals de RTX PRO 2000 Blackwell^),
echo installeer dan EERST het nieuwste stuurprogramma via de NVIDIA App.
echo Zorg voor internet. Het duurt 10 tot 45 minuten.
echo.

rem ---------- 1. installatiemap ----------
set "DOEL=C:\meelezen"
set "INVOER="
set /p "INVOER=In welke map installeren? [Enter = C:\meelezen]: "
if defined INVOER set "DOEL=%INVOER:"=%"
if "%DOEL:~-1%"=="\" set "DOEL=%DOEL:~0,-1%"
echo.
echo Installatiemap: %DOEL%

rem ---------- 2. bestanden kopieren ----------
if /i "%BRON%"=="%DOEL%" goto gekopieerd
echo [1/8] Bestanden kopieren...
set "UITSLUIT=config.toml bijbel.json psalmen.json formulieren.json dienst-*.json"
if exist "%DOEL%\data\dienst.json" set "UITSLUIT=%UITSLUIT% dienst.json"
robocopy "%BRON%" "%DOEL%" /E /NFL /NDL /NJH /NJS /NP /XD .venv __pycache__ /XF %UITSLUIT% >nul
if errorlevel 8 (
  echo Kopieren naar %DOEL% is mislukt. Heeft u schrijfrechten op die map?
  pause
  exit /b 1
)
:gekopieerd
cd /d "%DOEL%"

rem ---------- 3. gegevens van de oude computer ----------
set "OVER="
set "BUREAU="
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "BUREAU=%%d"
for %%f in ("!BUREAU!\meelezen-overzetten.zip" "%BRON%\meelezen-overzetten.zip" "%USERPROFILE%\Desktop\meelezen-overzetten.zip" "%USERPROFILE%\OneDrive\Desktop\meelezen-overzetten.zip" "%USERPROFILE%\OneDrive\Bureaublad\meelezen-overzetten.zip" "%USERPROFILE%\Downloads\meelezen-overzetten.zip") do (
  if not defined OVER if exist "%%~f" set "OVER=%%~f"
)
if defined OVER (
  echo.
  echo Gevonden: !OVER!
  choice /c JN /m "[2/8] Instellingen en gegevens van de oude computer terugzetten"
  if !errorlevel!==1 (
    tar -x -f "!OVER!" -C "%DOEL%"
    if errorlevel 1 (echo Terugzetten mislukt.) else (echo Gegevens van de oude computer teruggezet.)
  )
) else (
  echo [2/8] Geen meelezen-overzetten.zip gevonden: nieuwe installatie met standaardinstellingen.
)

rem ---------- 4. Python, onderdelen, ffmpeg ----------
echo.
echo [3/8] Python, onderdelen en Ollama installeren ^(dit duurt even^)...
set "MEELEZEN_STIL=1"
call "%DOEL%\installeren.bat"
if errorlevel 1 exit /b 1
set "MEELEZEN_STIL="
set "PY=%DOEL%\.venv\Scripts\python.exe"
rem ffmpeg/deno die winget net installeerde staan nog niet in PATH van dit venster
for /d %%d in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do for /d %%e in ("%%d\ffmpeg-*") do set "PATH=%%e\bin;!PATH!"
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"

rem ---------- 5. instellingen ----------
echo.
echo [4/8] Instellingen klaarzetten...
"%PY%" -m meelezen.inrichten "%DOEL%"

rem ---------- 6. Bijbel en psalmboek ----------
echo.
if exist "%DOEL%\data\bijbel.json" (
  echo [5/8] Bijbel staat er al.
) else (
  echo [5/8] Statenvertaling ophalen...
  "%PY%" -m meelezen.bijbel_ophalen
)
if exist "%DOEL%\data\psalmen.json" (
  echo       Psalmboek staat er al.
) else (
  echo       Psalmboek ophalen...
  "%PY%" -m meelezen.psalmen
)
if exist "%DOEL%\data\formulieren.json" (
  echo       Formulieren staan er al.
) else (
  echo       Formulieren ophalen...
  "%PY%" -m meelezen.formulieren
)
if exist "%DOEL%\data\henry.db" (echo       Matthew Henry staat klaar.) else (echo       Let op: data\henry.db ontbreekt, de verklaring van Matthew Henry werkt dan niet.)

rem ---------- 7. spraakmodel ----------
echo.
echo [6/8] Spraakmodel voor de spraakherkenning ophalen ^(eenmalig, enkele honderden MB^)...
"%PY%" -c "import logging; logging.basicConfig(level=logging.INFO, format='      %%(message)s'); from meelezen.config import laad; from meelezen import stt; stt.maak(laad()); print('      Spraakherkenning klaar')"


rem ---------- 8. snelkoppelingen en Windows ----------
echo.
echo [7/8] Snelkoppeling "Meelezen" op het bureaublad maken...
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Meelezen.lnk'); $s.TargetPath='%DOEL%\start.bat'; $s.WorkingDirectory='%DOEL%'; $s.IconLocation='%SystemRoot%\System32\imageres.dll,189'; $s.Save()"

echo.
choice /c JN /m "Meelezen automatisch starten (livestream) als u zich aanmeldt op deze computer"
if %errorlevel%==1 (
  powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Meelezen live.lnk'); $s.TargetPath='%DOEL%\start-live.bat'; $s.WorkingDirectory='%DOEL%'; $s.WindowStyle=7; $s.Save()"
  echo Automatisch starten staat aan.
)

echo.
choice /c JN /m "Slaapstand uitzetten zolang de computer aan de stroom zit (aanbevolen voor live)"
if %errorlevel%==1 (
  powercfg /change standby-timeout-ac 0
  powercfg /change hibernate-timeout-ac 0
  echo Slaapstand aan de stroom staat uit.
)

echo.
choice /c JN /m "Telefoons in het eigen netwerk toegang geven (Windows Firewall, poort 8080)"
if %errorlevel%==1 (
  echo Bevestig de vraag van Windows met Ja.
  powershell -NoProfile -Command "Start-Process netsh -Verb RunAs -Wait -ArgumentList 'advfirewall firewall add rule name=Meelezen dir=in action=allow protocol=TCP localport=8080'"
)

rem ---------- 9. internet via Tailscale ----------
echo.
echo [8/8] Publiceren op internet ^(Tailscale Funnel^)
echo   Let op: verwijder of hernoem EERST de oude computer in Tailscale
echo   ^(https://login.tailscale.com/admin/machines^), anders krijgt deze
echo   computer de naam meelezen-1 en werken de QR-codes niet meer.
choice /c JN /m "Tailscale installeren en instellen"
if %errorlevel%==2 goto klaar
set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
if not exist "%TS%" winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements
if not exist "%TS%" (
  echo Tailscale is niet gevonden. Installeer het via https://tailscale.com/download en voer daarna uit:
  echo   tailscale up --hostname=meelezen
  echo   tailscale funnel --bg 8080
  goto klaar
)
echo Er opent een browser: log in met hetzelfde account als op de oude computer.
"%TS%" up --hostname=meelezen
"%TS%" funnel --bg 8080
"%TS%" funnel status

:klaar
echo.
echo ==========================================================
"%PY%" -m meelezen.controle
echo ==========================================================
echo.
echo Klaar. Start Meelezen met de snelkoppeling "Meelezen" op het bureaublad.
echo Op deze computer: http://localhost:8080
echo.
choice /c JN /m "Meelezen nu starten"
if %errorlevel%==1 start "Meelezen" /d "%DOEL%" "%DOEL%\start.bat"
endlocal
