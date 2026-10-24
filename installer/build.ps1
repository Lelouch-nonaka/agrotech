#requires -Version 5.1
<#
.SYNOPSIS
    Сборка дистрибутива «Агро-Радара»: ZIP с приложением и установщиком.

.DESCRIPTION
    Создаёт installer\dist\AgroRadar-<version>.zip, внутри:
      AgroRadar-<version>\app\...      — приложение
      AgroRadar-<version>\installer\   — Install.cmd, install.ps1
    На другом ПК достаточно распаковать архив и запустить installer\Install.cmd.

.PARAMETER Version
    Версия в имени архива (по умолчанию 2.0).

.PARAMETER IncludeEnv
    Положить в архив .env с ключом AnyModel (ИИ-Агроном заработает сразу).
    По умолчанию .env исключается. Не публикуйте такой архив публично.
#>
param(
    [string]$Version = '2.0',
    [switch]$IncludeEnv
)

$ErrorActionPreference = 'Stop'
$script:InstallerDir = if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) { (Get-Location).Path } else { $PSScriptRoot }
$script:ProjectRoot = Split-Path -Parent $script:InstallerDir
$script:DistDir = Join-Path $script:InstallerDir 'dist'
$script:Staging = Join-Path $script:DistDir '.staging'
$script:Payload = Join-Path $script:Staging "AgroRadar-$Version"
$script:ZipPath = Join-Path $script:DistDir "AgroRadar-$Version.zip"

function Write-Step { param([string]$Text) Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok { param([string]$Text) Write-Host "    [OK] $Text" -ForegroundColor Green }

$skipDirs = @('venv', '__pycache__', 'shots', 'dist', 'installer', '.git', '.vs', '.idea', 'node_modules', '.tmp')
$skipFiles = @('server.log', 'Thumbs.db', '.DS_Store')
if (-not $IncludeEnv) { $skipFiles += '.env' }
$skipPatterns = @('*.pyc', '*.log', '*.zip')

function Copy-Tree {
    param([string]$Source, [string]$Destination)
    if (-not (Test-Path $Destination)) { New-Item -ItemType Directory -Path $Destination -Force | Out-Null }
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        if ($item.PSIsContainer) {
            if ($skipDirs -contains $item.Name) { continue }
            Copy-Tree -Source $item.FullName -Destination (Join-Path $Destination $item.Name)
            continue
        }
        if ($skipFiles -contains $item.Name) { continue }
        $skip = $false
        foreach ($p in $skipPatterns) { if ($item.Name -like $p) { $skip = $true; break } }
        if (-not $skip) {
            Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $Destination $item.Name) -Force
        }
    }
}

try {
    Write-Host ''
    Write-Host '  Агро-Радар — сборка дистрибутива' -ForegroundColor Green
    Write-Host '  ================================'
    Write-Step 'Подготовка'
    if (Test-Path $script:Staging) { Remove-Item -Recurse -Force $script:Staging }
    New-Item -ItemType Directory -Path $script:Payload -Force | Out-Null

    Copy-Tree -Source $script:ProjectRoot -Destination (Join-Path $script:Payload 'app')

    $installerDst = Join-Path $script:Payload 'installer'
    New-Item -ItemType Directory -Path $installerDst -Force | Out-Null
    foreach ($f in @('install.ps1', 'Install.cmd', 'Uninstall.cmd', 'README.md', 'app.ico')) {
        $src = Join-Path $script:InstallerDir $f
        if (Test-Path $src) { Copy-Item $src (Join-Path $installerDst $f) -Force }
    }
    Write-Ok "Скопировано в $script:Payload"

    Write-Step 'Упаковка'
    if (Test-Path $script:ZipPath) { Remove-Item -LiteralPath $script:ZipPath -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($script:Staging, $script:ZipPath)
    if (-not (Test-Path $script:ZipPath)) { throw 'Архив не создан.' }

    $size = [math]::Round((Get-Item $script:ZipPath).Length / 1MB, 1)
    $count = ([System.IO.Compression.ZipFile]::OpenRead($script:ZipPath)).Entries.Count
    Write-Ok "ZIP готов: $script:ZipPath ($size МБ, файлов: $count)"

    Remove-Item -Recurse -Force $script:Staging
    Write-Host ''
    if ($IncludeEnv) {
        Write-Host '  [!] В архив включён .env с ключом AnyModel — не публикуйте его.' -ForegroundColor Yellow
    }
    Write-Host '  Готово. На другом ПК: распаковать и запустить installer\Install.cmd' -ForegroundColor Green
    Write-Host ''
} catch {
    Write-Host ("ОШИБКА: {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}
