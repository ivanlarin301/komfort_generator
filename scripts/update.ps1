# Обновление системы карточек «Комфорт» (FR-11). Запускается из ОБНОВЛЕНИЕ.bat.
# Подтягивает свежую версию из git (если проект установлен через git) и повторяет установку — она идемпотентна.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

Write-Host "Обновление системы карточек «Комфорт»" -ForegroundColor White
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git -and (Test-Path -LiteralPath (Join-Path $Root ".git"))) {
    Write-Host "==> Скачиваю новую версию (git pull)…" -ForegroundColor Cyan
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & git pull --ff-only 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    $output | ForEach-Object { Write-Host "    $_" }
    if ($code -ne 0) {
        Write-Host "ОШИБКА: обновление не скачалось (код $code)." -ForegroundColor Red
        Write-Host "Что сделать: проверьте интернет. Если в папке меняли файлы системы — отправьте этот текст владельцу."
        exit 1
    }
} else {
    Write-Host "Проект установлен без git. Чтобы обновиться:" -ForegroundColor Yellow
    Write-Host "  1) скачайте свежий архив проекта у владельца;"
    Write-Host "  2) распакуйте его поверх этой папки (папки output и input не трогайте);"
    Write-Host "  3) запустите ОБНОВЛЕНИЕ.bat ещё раз — он доустановит нужное."
}

Write-Host ""
Write-Host "==> Проверяю установку…" -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup.ps1")
exit $LASTEXITCODE
