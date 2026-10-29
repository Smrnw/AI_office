@echo off
rem Install AI Office: Python check, .venv, data folder, desktop shortcut, first launch.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\install-windows.ps1" %*
if errorlevel 1 pause
