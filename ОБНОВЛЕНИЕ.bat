@echo off
rem Komfort cards: update to the latest version. Double-click this file.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update.ps1"
set "KC_EXIT=%ERRORLEVEL%"
echo.
if not defined KOMFORT_NO_PAUSE pause
exit /b %KC_EXIT%
