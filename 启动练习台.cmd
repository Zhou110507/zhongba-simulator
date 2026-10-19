@echo off
cd /d "%~dp0"
python -m billiards.webapp --port 8766 --open
if errorlevel 1 pause
