@echo off
chcp 65001 >nul
cd /d "%~dp0"
title FlowPhoto Host
echo.
where node >nul 2>&1
if errorlevel 1 (
    echo Node.js не найден. Установи с https://nodejs.org ^(LTS^)
    pause
    exit /b 1
)
node "%~dp0flowphoto-host\server.js"
pause