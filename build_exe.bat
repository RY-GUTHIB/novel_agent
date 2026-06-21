@echo off
chcp 65001 >nul 2>&1
title novel_agent EXE Builder

echo ============================================
echo  novel_agent EXE Builder
echo  Packs into a single .exe for distribution
echo ============================================
echo.

if not exist "%~dp0venv" (
    echo [ERROR] Please run start_gui.bat first to install dependencies
    pause
    exit /b 1
)

echo [1/3] Installing PyInstaller...
"%~dp0venv\Scripts\pip.exe" install pyinstaller -i https://mirrors.aliyun.com/pypi/simple/
if errorlevel 1 (
    "%~dp0venv\Scripts\pip.exe" install pyinstaller
)

if exist "%~dp0dist" rmdir /s /q "%~dp0dist"
if exist "%~dp0build" rmdir /s /q "%~dp0build"

echo.
echo [2/3] Building .exe (2-5 minutes)...
echo.

"%~dp0venv\Scripts\pyinstaller.exe" ^
    --name "novel_agent" ^
    --onefile ^
    --windowed ^
    --add-data "novel_agent;novel_agent" ^
    --add-data "vendor;vendor" ^
    --collect-submodules "novel_agent" ^
    gui_main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed
    pause
    exit /b 1
)

echo.
echo [3/3] Copying launcher...
copy /y "%~dp0launch_novel_agent.bat" "%~dp0dist\launch_novel_agent.bat" >nul

echo ============================================
echo  [OK] Build complete!
echo.
echo  Output:
echo    %~dp0dist\novel_agent.exe
echo    %~dp0dist\launch_novel_agent.bat
echo.
echo  Usage:
echo    1. Copy both files to the target machine
echo    2. Double-click launch_novel_agent.bat
echo    3. Data saves to: novel_agent_data\
echo ============================================
pause