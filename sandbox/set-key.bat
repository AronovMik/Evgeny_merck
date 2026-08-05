@echo off
REM Запись ключа API в sandbox\.env (Windows).
REM Запуск:  sandbox\set-key.bat
REM Ключ никуда, кроме sandbox\.env, не попадает. Файл в .gitignore.

setlocal enabledelayedexpansion
cd /d "%~dp0.."

set /p KEY=Вставьте ключ API и нажмите Enter:

if "%KEY%"=="" (
  echo Ключ пустой - ничего не записано.
  exit /b 1
)

if not exist "sandbox\.env" (
  if exist "sandbox\.env.example" (copy /y "sandbox\.env.example" "sandbox\.env" >nul) else (type nul > "sandbox\.env")
)

REM Существующие настройки сохраняем, меняем только строку с ключом.
findstr /v /b "OPENAI_API_KEY=" "sandbox\.env" > "sandbox\.env.tmp"
> "sandbox\.env" echo OPENAI_API_KEY=%KEY%
type "sandbox\.env.tmp" >> "sandbox\.env"
del "sandbox\.env.tmp"
set KEY=

echo Готово. Ключ записан в sandbox\.env
echo.
echo Запуск песочницы:  python sandbox\app.py
endlocal
