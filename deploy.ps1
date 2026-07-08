# Flow Studio — залить изменения на GitHub (FlowNote + FlowPhoto на Render)
# Запуск: двойной клик deploy.bat

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "=== Flow Studio — деплой ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path ".git")) {
    Write-Host "Ошибка: здесь нет git. Открой папку проекта с репозиторием." -ForegroundColor Red
    Read-Host "Enter"
    exit 1
}

$msg = Read-Host "Сообщение коммита (Enter = обновление)"
if ([string]::IsNullOrWhiteSpace($msg)) {
    $msg = "Обновление $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

git add -A
git reset HEAD .env 2>$null

$status = git status --porcelain
if (-not $status) {
    Write-Host "Нет изменений." -ForegroundColor Yellow
    Read-Host "Enter"
    exit 0
}

Write-Host ""
git status --short
Write-Host ""

git commit -m $msg
if ($LASTEXITCODE -ne 0) {
    Write-Host "Коммит не создан." -ForegroundColor Red
    Read-Host "Enter"
    exit 1
}

Write-Host ""
Write-Host "Отправка на GitHub..." -ForegroundColor Cyan
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Готово!" -ForegroundColor Green
    Write-Host "  FlowNote:  https://thxluv.github.io/flow-studio/" -ForegroundColor White
    Write-Host "  FlowPhoto: https://flowphoto.onrender.com/ (деплой ~3-5 мин)" -ForegroundColor White
    Write-Host ""
    Write-Host "Проверка: https://flowphoto.onrender.com/health" -ForegroundColor Gray
} else {
    Write-Host "Push не удался. Интернет / GitHub токен." -ForegroundColor Red
}

Write-Host ""
Read-Host "Enter"