@echo off
REM Classroom Lock — Teacher start.bat (Windows)
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==============================================
echo   Classroom Lock — Teacher
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

for %%p in (fastapi uvicorn websockets zeroconf) do (
    python -c "import %%p" 2>nul
    if errorlevel 1 (
        echo [..] Installiere %%p...
        python -m pip install %%p
        if errorlevel 1 python -m pip install --user %%p
        python -c "import %%p" 2>nul
        if errorlevel 1 (
            echo [FEHLER] %%p fehlt nach Installationsversuch
            pause & exit /b 1
        )
    )
)

echo [OK] Alle Abhaengigkeiten installiert
echo.
echo ==============================================
echo   Starte Teacher-Server...
echo ==============================================
echo.

python server\teacher_server.py
if errorlevel 1 (
    echo [FEHLER] Teacher abgestuerzt (Code: %ERRORLEVEL%)
    pause
)
