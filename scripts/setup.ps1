# Установка системы карточек «Комфорт» на Windows 10/11 (FR-10).
# Запускается из УСТАНОВКА.bat. Безопасно запускать повторно: каждый шаг проверяет, сделан ли он.
# Ничего не требует от пользователя, кроме интернета; права администратора не нужны.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$Log = Join-Path $Root "setup.log"
"=== Установка $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') в $Root ===" | Out-File -FilePath $Log -Encoding utf8

function Write-Step([string]$text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan; "==> $text" | Out-File $Log -Append -Encoding utf8 }
function Write-Ok([string]$text) { Write-Host "    $text" -ForegroundColor Green; "    OK: $text" | Out-File $Log -Append -Encoding utf8 }
function Write-Info([string]$text) { Write-Host "    $text"; "    $text" | Out-File $Log -Append -Encoding utf8 }

function Invoke-Logged([string]$what, [scriptblock]$command) {
    # Runs a native command, mirrors its output to the log, throws a Russian error on a non-zero exit code.
    # PowerShell 5.1 turns native stderr into errors under "Stop" (uv prints progress there), so relax it here.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $command 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
        }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    $output | Out-File $Log -Append -Encoding utf8
    if ($code -ne 0) { throw "шаг «$what» не выполнен (код $code). Подробности в setup.log." }
    return $output
}

function Find-Uv {
    $candidates = @(
        (Get-Command uv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\uv\uv.exe")
    )
    foreach ($c in $candidates) { if ($c -and (Test-Path -LiteralPath $c)) { return $c } }
    return $null
}

function Find-Edge {
    $paths = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
    )
    foreach ($p in $paths) { if ($p -and (Test-Path -LiteralPath $p)) { return $p } }
    return $null
}

try {
    Write-Host "Установка системы карточек «Комфорт»" -ForegroundColor White
    Write-Host "Папка: $Root"
    if ($Root.Length -gt 80) {
        Write-Host ""
        Write-Host "ВНИМАНИЕ: папка проекта лежит слишком глубоко ($($Root.Length) символов в пути)." -ForegroundColor Yellow
        Write-Host "Windows ограничивает длину путей, и часть библиотек может не установиться."
        Write-Host "Лучше перенести папку ближе к корню диска, например D:\Комфорт, и запустить установку оттуда."
        "WARN: long project path ($($Root.Length) chars)" | Out-File $Log -Append -Encoding utf8
    }

    Write-Step "1/5 Менеджер окружения uv"
    $uv = Find-Uv
    if (-not $uv) {
        Write-Info "uv не найден — устанавливаю (официальный установщик astral.sh)…"
        try {
            Invoke-Logged "Установка uv" { powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" } | Out-Null
        } catch {
            Write-Info "Официальный установщик не сработал, пробую winget…"
            Invoke-Logged "Установка uv через winget" { winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements --silent } | Out-Null
        }
        $uv = Find-Uv
        if (-not $uv) { throw "uv установился, но не найден. Перезапустите компьютер и запустите установку ещё раз." }
    }
    Write-Ok "uv: $uv"

    Write-Step "2/5 Python 3.12 и библиотеки (первый раз — несколько минут)"
    Invoke-Logged "Установка Python и библиотек" { & $uv sync --frozen } | Out-Null
    $python = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) { throw "Окружение .venv не создано." }
    Write-Ok ((& $python --version) -join " ")

    Write-Step "3/5 Модель вырезки товара (~170 МБ, один раз)"
    $out = Invoke-Logged "Загрузка модели вырезки" { & $python -m komfort_cards setup-models }
    Write-Ok (($out | Where-Object { $_ -like "Модель*" }) -join " ")

    Write-Step "4/5 Браузерный движок для сборки карточек"
    $edge = Find-Edge
    if ($edge) {
        Write-Ok "найден: $edge"
    } else {
        Write-Info "Edge/Chrome не найден — ставлю встроенный движок Chromium…"
        Invoke-Logged "Установка Chromium" { & $python -m playwright install chromium } | Out-Null
        Write-Ok "Chromium установлен"
    }

    Write-Step "5/5 Самопроверка: собираю тестовую карточку"
    Invoke-Logged "Самопроверка" { & $python -m komfort_cards selftest } | Out-Null
    foreach ($dir in @("input", "output")) { New-Item -ItemType Directory -Force -Path (Join-Path $Root $dir) | Out-Null }
    Write-Ok "тестовая карточка: output\_selftest\card.png"

    Write-Host ""
    Write-Host "ГОТОВО. Система установлена." -ForegroundColor Green
    Write-Host "Дальше: откройте папку $Root в Codex и напишите «сделай карточки», прикрепив фото и таблицу."
    "=== Готово ===" | Out-File $Log -Append -Encoding utf8
    exit 0
}
catch {
    Write-Host ""
    Write-Host "ОШИБКА: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Что сделать: проверьте интернет и запустите установку ещё раз. Если не помогло — отправьте файл setup.log разработчику."
    "ОШИБКА: $($_.Exception.Message)`n$($_.ScriptStackTrace)" | Out-File $Log -Append -Encoding utf8
    exit 1
}
