@echo off
chcp 65001 >nul 2>&1
setlocal

set "PROJECT_DIR=%~dp0"
set "VENV_PYTHON=%PROJECT_DIR%venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" "%PROJECT_DIR%main.py"
) else (
    echo Python venv not found at %VENV_PYTHON%
    pause
)
