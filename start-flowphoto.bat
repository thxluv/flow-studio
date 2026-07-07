@echo off
chcp 65001 >nul
cd /d "%~dp0flowphoto-server"
title FlowPhoto Server
echo.
where python >nul 2>&1
if errorlevel 1 (
    echo Python не найден. Установи с https://www.python.org/downloads/
    pause
    exit /b 1
)
echo === FlowPhoto Server ===
echo Установка зависимостей (если нужно)...
python -m pip install -r requirements.txt -q
echo.
echo Открой в браузере: http://127.0.0.1:8000/
echo Остановка: Ctrl+C
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pause