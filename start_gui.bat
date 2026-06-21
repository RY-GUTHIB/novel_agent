@echo off
chcp 65001 >nul 2>&1
setlocal

set "PROJECT_DIR=%~dp0"
set "VENV_PYTHON=%PROJECT_DIR%venv\Scripts\pythonw.exe"

if exist "%VENV_PYTHON%" (
    start "" "%VENV_PYTHON%" "%PROJECT_DIR%gui_main.py"
) else (
    echo Python venv not found at %PROJECT_DIR%venv\Scripts\pythonw.exe
    pause
)
