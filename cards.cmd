@echo off
rem Komfort cards CLI wrapper: runs the project Python from .venv regardless of PATH.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Система не установлена: запустите УСТАНОВКА.bat двойным кликом.
  exit /b 2
)
".venv\Scripts\python.exe" -m komfort_cards %*
exit /b %ERRORLEVEL%
