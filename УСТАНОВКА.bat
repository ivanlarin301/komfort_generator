@echo off
rem Komfort cards: one-click setup. Double-click this file.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
set "KC_EXIT=%ERRORLEVEL%"
echo.
if not defined KOMFORT_NO_PAUSE pause
exit /b %KC_EXIT%
