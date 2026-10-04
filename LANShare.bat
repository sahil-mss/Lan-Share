@echo off
setlocal
cd /d "%~dp0"
title LANShare Desktop Launcher

echo ===================================================
echo               LANShare Desktop
echo   Locally Hosted Collaborative Shared Folders
echo ===================================================
echo.

rem Check for virtual environment
if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

rem Launch LANShare Server with browser auto-open and Local Client daemon
"%PYTHON_EXE%" run_server.py --port 7420 --browser --start-client %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [LANShare] Server exited with error code %ERRORLEVEL%.
    pause
)
endlocal
