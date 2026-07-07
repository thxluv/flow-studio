# Flow Studio — заливка изменений на GitHub Pages
# Запуск: правый клик → «Выполнить с PowerShell» или: .\deploy.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "=== Flow Studio — деплой на GitHub ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path ".git")) {
    Write-Host "Ошибка: папка не является git-репозиторием." -ForegroundColor Red
    Write-Host "Сначала выполни шаги из ДЕПЛОЙ.txt (git init + remote)."
    Read-Host "Нажми Enter для выхода"
    exit 1
}

$msg = Read-Host "Сообщение коммита (Enter = обновление сайта)"
if ([string]::IsNullOrWhiteSpace($msg)) {
    $msg = "Обновление сайта $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

$files = @(
    "index.html",
    "flowphoto.html",
    "flow-config.js",
    "public-config.json",
    "render.yaml",
    "deploy.ps1",
    "deploy.bat",
    "start-flowphoto.bat",
    "ДЕПЛОЙ.txt",
    "ПУБЛИЧНЫЙ-ЗАПУСК.txt",
    ".gitignore",
    "статус-проекта.txt",
    "план.txt",
    "обзор-проекта.txt",
    "сложные-задачи-позже.txt",
    "flowphoto-server"
)

git add @files 2>$null
git add -u

$status = git status --porcelain
if (-not $status) {
    Write-Host "Нет изменений для коммита." -ForegroundColor Yellow
    Read-Host "Нажми Enter для выхода"
    exit 0
}

Write-Host ""
Write-Host "Изменённые файлы:" -ForegroundColor Gray
git status --short
Write-Host ""

git commit -m $msg
if ($LASTEXITCODE -ne 0) {
    Write-Host "Коммит не создан." -ForegroundColor Red
    Read-Host "Нажми Enter для выхода"
    exit 1
}

Write-Host ""
Write-Host "Отправка на GitHub..." -ForegroundColor Cyan
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Готово! Сайт обновится через 1–2 минуты:" -ForegroundColor Green
    Write-Host "  https://thxluv.github.io/flow-studio/" -ForegroundColor White
    Write-Host "  FlowPhoto: start-flowphoto.bat -> http://127.0.0.1:8000/" -ForegroundColor White
} else {
    Write-Host ""
    Write-Host "Push не удался. Проверь интернет и вход в GitHub (токен)." -ForegroundColor Red
    Write-Host "Подсказка: см. ДЕПЛОЙ.txt → ШАГ 3б (Personal Access Token)"
}

Write-Host ""
Read-Host "Нажми Enter для выхода"