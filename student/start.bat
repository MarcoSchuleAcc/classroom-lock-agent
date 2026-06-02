@echo off
REM Classroom Lock — Student start.bat (Windows)
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==============================================
echo   Classroom Lock — Student
echo ==============================================

REM ─── Python ─────────────────────────────────────
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [FEHLER] Python nicht gefunden. Installiere von https://python.org
    pause & exit /b 1
)
for /f "tokens=2 delims= " %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [OK] Python: %PYVER%

REM ─── venv ───────────────────────────────────────
:venv
if exist "venv" (rmdir /s /q "venv" 2>nul)
echo [..] Erstelle venv...
python -m venv venv
if errorlevel 1 (echo [WARN] venv fehlgeschlagen — systemweit & goto :deps)
if not exist "venv\Scripts\activate.bat" (echo [WARN] activate.bat fehlt & goto :deps)
call venv\Scripts\activate.bat
if errorlevel 1 goto :deps
echo [OK] venv aktiviert
goto :deps

REM ─── Dependencies ──────────────────────────────
:deps
echo [..] Installiere Abhaengigkeiten in "%VIRTUAL_ENV%"...

python -c "import websockets" 2>nul
if errorlevel 1 (
    echo [..] Installiere websockets...
    python -m pip install websockets
    if errorlevel 1 (
        echo [..] Versuche --user...
        python -m pip install --user websockets
    )
    python -c "import websockets" 2>nul
    if errorlevel 1 (
        echo [FEHLER] websockets fehlt.
        pause & exit /b 1
    )
)

echo [..] Installiere numpy (für Mikrofon)...
python -c "import numpy" 2>nul
if errorlevel 1 (
    python -m pip install numpy
    if errorlevel 1 python -m pip install --user numpy
    python -c "import numpy" 2>nul
    if errorlevel 1 (echo [WARN] numpy fehlt — Mikrofon deaktiviert)
)

echo [..] Installiere sounddevice (für Mikrofon)...
python -c "import sounddevice" 2>nul
if errorlevel 1 (
    python -m pip install sounddevice
    if errorlevel 1 python -m pip install --user sounddevice
    python -c "import sounddevice" 2>nul
    if errorlevel 1 (echo [WARN] sounddevice fehlt — Mikrofon deaktiviert)
)

echo [OK] Installation abgeschlossen
echo.
echo ==============================================
echo   Starte Student-Agent...
echo ==============================================
echo.

REM Argumente parsen
set ARGS=--discover
if not "%1"=="" (
    if /i "%1"=="--teacher" set ARGS=--teacher %2
    if /i "%1"=="--classroom" set ARGS=--classroom %2
    if /i "%1"=="--discover" set ARGS=--discover
    echo %1|findstr /r "^[0-9]" >nul
    if errorlevel 1 (if "!ARGS!"=="--discover" set ARGS=--discover) else set ARGS=--teacher %1
)

echo python agent\student_agent.py %ARGS%
python agent\student_agent.py %ARGS%
if errorlevel 1 (
    echo [FEHLER] Agent abgestuerzt (Code: %ERRORLEVEL%)
    pause
)
