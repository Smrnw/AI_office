@echo off
rem Start AI Office (the desktop shortcut points here). Close this window to stop the office.
chcp 65001 >nul
cd /d "%~dp0"
title AI Office
if not exist ".venv\Scripts\python.exe" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\install-windows.ps1" -NoShortcut -NoLaunch
)
".venv\Scripts\python.exe" -m pixel_office.launcher
if errorlevel 1 pause
