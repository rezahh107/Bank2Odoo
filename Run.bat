@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
    echo Bank2Odoo: uv is not installed or not on PATH.
    echo Ask your technician to install uv and Python 3.13 once:
    echo https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)
rem Normal use is deliberately offline; run "uv sync --locked" once with Internet first.
uv run --offline --locked python -m bank2odoo.ui
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo Bank2Odoo could not start.
    echo For first-time setup, connect to the Internet and run:
    echo   uv python install 3.13
    echo   uv sync --locked
    echo Then double-click Run.bat again. If it still fails, contact the technician.
    pause
)
exit /b %APP_EXIT%
