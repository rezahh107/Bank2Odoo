@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
    echo Bank2Odoo requires uv. Install uv and retry.
    echo https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)
uv run --locked python -m bank2odoo
set "APP_EXIT=%ERRORLEVEL%"
pause
exit /b %APP_EXIT%
