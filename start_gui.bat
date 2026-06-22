@echo off
chcp 65001 >nul 2>&1
setlocal

set "PROJECT_DIR=%~dp0"
set "PYTHON=C:\Users\RY\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"

if exist "%PYTHON%" (
    start "" "%PYTHON%" "%PROJECT_DIR%gui_main.py"
) else (
    echo Python not found at %PYTHON%
    pause
)
