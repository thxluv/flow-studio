@echo off
chcp 65001 >nul
cd /d "%~dp0flowphoto-server"
title FlowPhoto — локально
echo.
where python >nul 2>&1
if errorlevel 1 (
    echo Python не найден: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo === FlowPhoto локально ===
echo.
echo Нужен FLOWPHOTO_VAULT_SECRET в переменных окружения.
echo Пример PowerShell:
echo   $env:FLOWPHOTO_VAULT_SECRET = "твой-секрет-минимум-32-символа"
echo.
python -m pip install -r requirements.txt -q
echo Браузер: http://127.0.0.1:8000/
echo Ctrl+C — остановка
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pause