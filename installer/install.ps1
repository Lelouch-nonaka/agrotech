#requires -Version 5.1
<#
.SYNOPSIS
    Установка «Агро-Радара» для текущего пользователя: Python, зависимости,
    ярлыки, запуск. Ничего не требует из установленного, кроме Windows и интернета.

.DESCRIPTION
    1. Копирует приложение в %LOCALAPPDATA%\AgroRadar\app.
    2. Ищет Python 3.9+. Если нет — скачивает официальный embeddable-архив
       python.org и ставит pip.
    3. Создаёт виртуальное окружение и ставит зависимости (fastapi, uvicorn,
       scikit-learn, pandas, numpy, openai, python-dotenv).
    4. Делает лаунчер и ярлыки, открывает браузер.

.PARAMETER Port
    Порт сервера (по умолчанию 8000).

.PARAMETER InstallRoot
    Нестандартный каталог установки (по умолчанию %LOCALAPPDATA%\AgroRadar).

.PARAMETER NoShortcuts
    Не создавать ярлыки на рабочем столе и в меню «Пуск».

.PARAMETER Uninstall
    Удалить установку.

.PARAMETER DryRun
    Показать план, ничего не менять.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\installer\install.ps1
#>
param(
    [int]$Port = 8000,
    [string]$InstallRoot,
    [switch]$NoShortcuts,
    [switch]$Uninstall,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
try {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $utf8
    $OutputEncoding = $utf8
} catch { }

$script:InstallerDir = if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) { (Get-Location).Path } else { $PSScriptRoot }
# Два варианта раскладки:
#   проект:      <корень>\main.py + <корень>\installer\
#   портативный: <корень>\app\main.py + <корень>\installer\   (так лежит в ZIP)
$script:ParentDir = Split-Path -Parent $script:InstallerDir
if (Test-Path (Join-Path $script:ParentDir 'main.py')) {
    $script:SourceRoot = $script:ParentDir
    $script:Layout = 'project'
} elseif (Test-Path (Join-Path $script:ParentDir 'app\main.py')) {
    $script:SourceRoot = Join-Path $script:ParentDir 'app'
    $script:Layout = 'portable'
} else {
    $script:SourceRoot = $script:ParentDir
    $script:Layout = 'unknown'
}
$script:Root = if ($InstallRoot) { [IO.Path]::GetFullPath($InstallRoot) } else { Join-Path $env:LOCALAPPDATA 'AgroRadar' }
$script:AppDir = Join-Path $script:Root 'app'
$script:VenvDir = Join-Path $script:Root 'venv'
$script:EmbeddedPython = Join-Path $script:Root 'python'
$script:LauncherPath = Join-Path $script:Root 'AgroRadar.cmd'
$script:MarkerPath = Join-Path $script:Root 'install.json'
$script:IconPath = Join-Path $script:Root 'AgroRadar.ico'
$script:Version = '2.0'
$script:ShortcutName = 'AgroRadar.lnk'
$script:ExplicitRoot = [bool]$InstallRoot

function Write-Step { param([string]$Text) Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok { param([string]$Text) Write-Host "    [OK] $Text" -ForegroundColor Green }
function Write-Info { param([string]$Text) Write-Host "    $Text" }
function Write-Warn { param([string]$Text) Write-Host "    [!] $Text" -ForegroundColor Yellow }

function Assert-SafeRoot {
    $root = [IO.Path]::GetFullPath($script:Root).TrimEnd([char[]]@('\', '/'))
    $forbidden = @()
    foreach ($raw in @($env:SystemDrive + '\', $env:LOCALAPPDATA, $env:APPDATA, $env:USERPROFILE,
                       $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:WINDIR)) {
        if ([string]::IsNullOrWhiteSpace($raw)) { continue }
        try {
            $full = [IO.Path]::GetFullPath($raw).TrimEnd([char[]]@('\', '/'))
            if ($full) { $forbidden += $full }
        } catch { }
    }
    if (-not $script:ExplicitRoot) {
        $expected = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'AgroRadar')).TrimEnd([char[]]@('\', '/'))
        if ($root -ne $expected) { throw "Внутренняя ошибка: неожиданный каталог установки '$root'." }
    }
    if ($forbidden -contains $root -or (($root -split '[\\/]' | Where-Object { $_ }).Count -lt 2)) {
        throw "Каталог '$root' системный — установка отменена."
    }
}

function Copy-AppTree {
    param([string]$Source, [string]$Destination)
    $skipDirs = @('venv', '__pycache__', 'installer', 'shots', 'dist', '.git', '.vs', '.idea', 'node_modules')
    $skipFiles = @('server.log', 'Thumbs.db', '.DS_Store')
    $skipPatterns = @('*.pyc', '*.log', '*.zip')
    if (-not (Test-Path $Destination)) { New-Item -ItemType Directory -Path $Destination -Force | Out-Null }
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        if ($item.PSIsContainer) {
            if ($skipDirs -contains $item.Name) { continue }
            Copy-AppTree -Source $item.FullName -Destination (Join-Path $Destination $item.Name)
            continue
        }
        if ($skipFiles -contains $item.Name) { continue }
        $skip = $false
        foreach ($p in $skipPatterns) { if ($item.Name -like $p) { $skip = $true; break } }
        if (-not $skip) { Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $Destination $item.Name) -Force }
    }
}

function Test-PythonExe {
    param([string]$Exe)
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $false }
    try {
        & $Exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-SystemPython {
    $candidates = @()
    foreach ($cmd in @('py', 'python', 'python3')) {
        $c = Get-Command $cmd -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $c) { continue }
        if ($cmd -eq 'py') {
            try {
                $out = & py -3 -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $out) { $candidates += $out.Trim() }
            } catch { }
        } else {
            $candidates += $c.Source
        }
    }
    foreach ($exe in $candidates) {
        if (Test-PythonExe -Exe $exe) { return $exe }
    }
    return $null
}

function Install-EmbeddedPython {
    $zip = Join-Path $env:TEMP 'python-embed-agro-radar.zip'
    $url = 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip'
    Write-Info "Скачиваю Python 3.12 embeddable: $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    if (Test-Path $script:EmbeddedPython) { Remove-Item -Recurse -Force $script:EmbeddedPython }
    Expand-Archive -LiteralPath $zip -DestinationPath $script:EmbeddedPython -Force
    Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue

    $pth = Get-ChildItem -LiteralPath $script:EmbeddedPython -Filter 'python*._pth' | Select-Object -First 1
    if ($pth) {
        $lines = Get-Content -LiteralPath $pth.FullName
        $lines = $lines | Where-Object { $_ -ne 'import site' -and $_ -ne '#import site' }
        $lines += 'Lib\site-packages'
        $lines += 'import site'
        Set-Content -LiteralPath $pth.FullName -Value $lines -Encoding ASCII
    }

    $py = Join-Path $script:EmbeddedPython 'python.exe'
    $getpip = Join-Path $env:TEMP 'get-pip.py'
    Write-Info 'Ставлю pip в embeddable-Python…'
    Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getpip -UseBasicParsing
    & $py $getpip --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить pip в embeddable-Python.' }
    Remove-Item -LiteralPath $getpip -Force -ErrorAction SilentlyContinue
    return $py
}

function Ensure-Environment {
    $systemPy = Find-SystemPython
    if ($systemPy) {
        Write-Ok "Системный Python: $systemPy"
        if (-not (Test-Path (Join-Path $script:VenvDir 'Scripts\python.exe'))) {
            Write-Info 'Создаю виртуальное окружение…'
            & $systemPy -m venv $script:VenvDir
            if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать venv.' }
        }
        $py = Join-Path $script:VenvDir 'Scripts\python.exe'
    } else {
        Write-Warn 'Python 3.9+ не найден — ставлю embeddable-сборку.'
        $py = Install-EmbeddedPython
    }

    Write-Info 'Ставлю зависимости (это может занять пару минут)…'
    & $py -m pip install --upgrade pip --quiet --disable-pip-version-check
    & $py -m pip install -r (Join-Path $script:AppDir 'requirements.txt') --quiet --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости.' }
    Write-Ok 'Зависимости установлены.'
    return $py
}

function Write-Launcher {
    param([string]$PythonExe)
    $py = if ($PythonExe -like '*\venv\*') { '%ROOT%venv\Scripts\python.exe' } else { $PythonExe }
    $content = @"
@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Agro-Radar
set "ROOT=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%ROOT%app"

set "PY=$py"
if not exist "%PY%" set "PY=python"

start "" /b "%PY%" -X utf8 -c "import time,webbrowser; time.sleep(1.5); webbrowser.open('http://127.0.0.1:$Port/')"
"%PY%" -X utf8 main.py
if errorlevel 1 pause
"@
    [IO.File]::WriteAllText($script:LauncherPath, $content, (New-Object System.Text.UTF8Encoding($false)))
}

function New-Shortcuts {
    if ($NoShortcuts) { Write-Info 'Ярлыки не создаются (-NoShortcuts).'; return }
    $shell = New-Object -ComObject WScript.Shell
    $targets = @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) $script:ShortcutName),
        (Join-Path ([Environment]::GetFolderPath('Programs')) $script:ShortcutName)
    )
    foreach ($path in $targets) {
        $lnk = $shell.CreateShortcut($path)
        $lnk.TargetPath = $script:LauncherPath
        $lnk.WorkingDirectory = $script:Root
        $lnk.Description = 'Агро-Радар — аналитика полей'
        if (Test-Path $script:IconPath) { $lnk.IconLocation = $script:IconPath }
        $lnk.Save()
    }

    # ярлык удаления в меню «Пуск»
    $uninstallCmd = Join-Path $script:Root 'Uninstall.cmd'
    if (Test-Path $uninstallCmd) {
        $u = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'Удалить Агро-Радар.lnk'))
        $u.TargetPath = $uninstallCmd
        $u.WorkingDirectory = $script:Root
        $u.Description = 'Удалить Агро-Радар'
        $u.Save()
        Write-Ok "Ярлыки: рабочий стол, «Пуск» и «Удалить Агро-Радар»"
    } else {
        Write-Ok "Ярлыки: рабочий стол и меню «Пуск»"
    }
}

function Write-Uninstaller {
    # Отдельный деинсталлятор: ярлык + Uninstall.cmd в каталоге установки
    $body = @'
param([string]$Root)
$ErrorActionPreference = 'SilentlyContinue'

# Перезапускаемся из TEMP: иначе скрипт держит собственную папку и мешает удалению
if ($PSCommandPath -and -not $env:AGRO_UNINST_RELOC) {
    $tmp = Join-Path $env:TEMP 'agro_radar_uninstall.ps1'
    Copy-Item -LiteralPath $PSCommandPath -Destination $tmp -Force
    $env:AGRO_UNINST_RELOC = '1'
    & powershell -NoProfile -ExecutionPolicy Bypass -File $tmp -Root $Root
    exit
}

Write-Host ''
Write-Host '  Удаление Агро-Радара' -ForegroundColor Yellow
Write-Host '  ====================='
$links = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'AgroRadar.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'AgroRadar.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'Удалить Агро-Радар.lnk')
)
foreach ($p in $links) {
    if (Test-Path -LiteralPath $p) {
        Remove-Item -LiteralPath $p -Force
        Write-Host "  удалён $p"
    }
}

$removed = $false
for ($i = 0; $i -lt 10 -and -not $removed; $i++) {
    Get-Process | Where-Object {
        $_.Path -and $_.Path.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)
    } | Stop-Process -Force
    foreach ($proc in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
        if ($proc.ProcessId -eq $PID) { continue }        # не убиваем себя
        if ($proc.CommandLine -and
            $proc.CommandLine.IndexOf($Root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Milliseconds 1200
    Remove-Item -LiteralPath $Root -Recurse -Force
    $removed = -not (Test-Path -LiteralPath $Root)
}

if ($removed) {
    Write-Host '  Готово: приложение и ярлыки удалены.' -ForegroundColor Green
} else {
    # остатки (антивирус/индексатор держат файлы) удаляем отдельным процессом
    $bat = Join-Path $env:TEMP 'agro_radar_cleanup.bat'
    $lines = @(
        '@echo off',
        'for /L %%i in (1,1,30) do (',
        ('  rmdir /s /q "{0}"' -f $Root),
        ('  if not exist "{0}" goto done' -f $Root),
        '  timeout /t 3 /nobreak >nul',
        ')',
        ':done',
        'del /f /q "%~f0"'
    )
    Set-Content -LiteralPath $bat -Value $lines -Encoding ASCII
    Start-Process -FilePath $bat -WindowStyle Hidden
    Write-Host '  Готово: ярлыки удалены, файлы удаляются в фоне (до минуты).' -ForegroundColor Green
}
Start-Sleep -Seconds 1
'@
    $ps1 = Join-Path $script:Root 'uninstall.ps1'
    [IO.File]::WriteAllText($ps1, $body, (New-Object System.Text.UTF8Encoding($true)))
    $cmd = "@echo off`r`nchcp 65001 >nul`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0uninstall.ps1`" -Root `"%~dp0`"`r`npause`r`n"
    [IO.File]::WriteAllText((Join-Path $script:Root 'Uninstall.cmd'), $cmd,
                            (New-Object System.Text.UTF8Encoding($false)))
    Write-Ok "Деинсталлятор: $(Join-Path $script:Root 'Uninstall.cmd')"
}

function Test-AppImport {
    param([string]$PythonExe)
    $out = & $PythonExe -X utf8 -c "import sys; sys.path.insert(0, r'$($script:AppDir)'); import main; print('ok')" 2>&1
    if ($LASTEXITCODE -ne 0) { throw ("Приложение не импортируется: {0}" -f ($out -join ' ')) }
}

function Show-Plan {
    Write-Host ''
    Write-Host '  Агро-Радар — установка' -ForegroundColor Green
    Write-Host '  ======================'
    Write-Info "Источник:   $script:SourceRoot"
    Write-Info "Каталог:    $script:Root"
    Write-Info "Порт:       $Port"
    Write-Info "Ярлыки:     $(if ($NoShortcuts) { 'нет' } else { 'рабочий стол + Пуск' })"
    $sys = Find-SystemPython
    if ($sys) { Write-Info "Python:     $sys" } else { Write-Info "Python:     будет скачан (embeddable 3.12)" }
}

function Invoke-Install {
    if ($Port -lt 1 -or $Port -gt 65535) { throw "Некорректный порт: $Port" }
    if (-not (Test-Path (Join-Path $script:SourceRoot 'main.py'))) {
        throw ("Не найден main.py. Распакуйте архив целиком: рядом с папкой installer " +
               "должна лежать папка app (в ней main.py). Проверено: $script:SourceRoot")
    }
    Write-Step 'Копирование приложения'
    New-Item -ItemType Directory -Path $script:Root -Force | Out-Null
    $staging = Join-Path $script:Root '.app-staging'
    if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
    Copy-AppTree -Source $script:SourceRoot -Destination $staging
    if (Test-Path $script:AppDir) { Remove-Item -Recurse -Force $script:AppDir }
    Move-Item -LiteralPath $staging -Destination $script:AppDir
    Write-Ok "Файлы: $script:AppDir"
    if (-not (Test-Path (Join-Path $script:AppDir '.env'))) {
        Write-Warn 'Файл .env не найден: ИИ-Агроном будет работать без LLM.'
        Write-Info 'Включить LLM: скопируйте .env.example → .env и впишите ANYMODEL_API_KEY.'
    }

    Write-Step 'Python и зависимости'
    $py = Ensure-Environment

    Write-Step 'Лаунчер и ярлыки'
    $iconSrc = Join-Path $script:InstallerDir 'app.ico'
    if (Test-Path $iconSrc) { Copy-Item $iconSrc $script:IconPath -Force }
    Write-Launcher -PythonExe $py
    Write-Ok "Лаунчер: $script:LauncherPath"
    Write-Uninstaller
    New-Shortcuts

    Write-Step 'Проверка'
    Test-AppImport -PythonExe $py
    Write-Ok 'Приложение импортируется.'

    $marker = [ordered]@{
        product = 'Agro-Radar'; version = $script:Version
        installed_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
        port = $Port; python = $py; root = $script:Root
    }
    [IO.File]::WriteAllText($script:MarkerPath, ($marker | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))

    Write-Host ''
    Write-Host '  Готово! «Агро-Радар» установлен.' -ForegroundColor Green
    Write-Info "Запуск:  $script:LauncherPath"
    Write-Info "Адрес:   http://127.0.0.1:$Port/"
    Write-Info "Удалить: ярлык «Удалить Агро-Радар» в меню «Пуск» (или Uninstall.cmd в папке установки)"
    Write-Host ''
    try { Start-Process -FilePath $script:LauncherPath -WindowStyle Minimized } catch { }
}

function Stop-OurProcesses {
    # Останавливает процессы приложения: и по пути, и по командной строке
    # (лаунчер — это cmd.exe из system32, его путь не внутри каталога установки).
    $prefix = $script:Root.TrimEnd([char[]]@('\', '/')) + '\'
    $ids = New-Object System.Collections.Generic.HashSet[int]
    foreach ($proc in @(Get-Process -ErrorAction SilentlyContinue)) {
        try {
            if ($proc.Path -and $proc.Path.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                [void]$ids.Add($proc.Id)
            }
        } catch { }
    }
    foreach ($proc in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
        if ($proc.ProcessId -eq $PID) { continue }
        if ($proc.CommandLine -and
            $proc.CommandLine.IndexOf($script:Root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            [void]$ids.Add([int]$proc.ProcessId)
        }
    }
    foreach ($id in $ids) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
    if ($ids.Count -gt 0) {
        Write-Info "Остановлено процессов приложения: $($ids.Count)"
        Start-Sleep -Milliseconds 700
    }
}

function Invoke-Uninstall {
    Write-Step 'Удаление'
    $shell = New-Object -ComObject WScript.Shell
    foreach ($path in @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) $script:ShortcutName),
        (Join-Path ([Environment]::GetFolderPath('Programs')) $script:ShortcutName))) {
        if (Test-Path $path) { Remove-Item -LiteralPath $path -Force; Write-Ok "Удалён $path" }
    }
    if (Test-Path $script:Root) {
        Stop-OurProcesses
        $removed = $false
        for ($i = 0; $i -lt 3 -and -not $removed; $i++) {
            try {
                Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction Stop
                $removed = $true
            } catch {
                Start-Sleep -Milliseconds 800
            }
        }
        if ($removed) {
            Write-Ok "Удалён $script:Root"
        } else {
            Write-Warn "Не удалось удалить $script:Root — закройте окно «Агро-Радар» и повторите."
        }
    } else {
        Write-Info 'Не установлено — удалять нечего.'
    }
}

# ------------------------------------------------------------------ main ----
try {
    Write-Host ''
    Write-Host '  Агро-Радар — установщик' -ForegroundColor Green
    Write-Host '  ======================='
    Assert-SafeRoot
    if ($Uninstall) {
        if ($DryRun) { Write-Step 'План удаления'; Write-Info "Каталог: $script:Root"; return }
        Invoke-Uninstall
    } elseif ($DryRun) {
        Show-Plan
        Write-Host ''
        Write-Host '  Dry-run: ничего не изменено.' -ForegroundColor Green
    } else {
        Invoke-Install
    }
} catch {
    Write-Host ''
    Write-Host ("ОШИБКА: {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}
