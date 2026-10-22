@echo off
cd /d "%~dp0"
python -m billiards.launcher
if errorlevel 1 pause
