@echo off
REM Запуск песочницы одной командой (Windows): sandbox\run.bat
cd /d "%~dp0.."
if not exist "sandbox\.env" (
  echo Нет sandbox\.env - работаю в mock-режиме, запросы к API не уходят.
  echo Чтобы подключить модель: скопируйте sandbox\.env.example в sandbox\.env и впишите ключ.
  echo.
)
python sandbox\app.py %*
