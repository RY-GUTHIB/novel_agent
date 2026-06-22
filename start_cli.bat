@echo off
chcp 65001 >nul 2>&1
setlocal

set "PROJECT_DIR=%~dp0"
set "PYTHON=C:\Users\RY\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if exist "%PYTHON%" (
    "%PYTHON%" "%PROJECT_DIR%main.py"
) else (
    echo Python not found at %PYTHON%
    pause
)
