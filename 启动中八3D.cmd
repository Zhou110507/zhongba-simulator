@echo off
cd /d "%~dp0"
if exist "runtime\python.exe" (
    "runtime\python.exe" -X utf8 -m billiards.launcher
) else (
    python -X utf8 -m billiards.launcher
)
if errorlevel 1 pause
