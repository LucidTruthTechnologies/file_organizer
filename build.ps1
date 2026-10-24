# build.ps1 - build file-organizer.exe on a Windows machine.
# Version: 1.0.0
# Last modified: 2026-10-24
#
# USAGE:
#     .\build.ps1                 build dist\file-organizer.exe
#     .\build.ps1 -SkipTests      build without running pytest first
#     .\build.ps1 -Help
#
# Needs: Python 3.11+ on PATH, internet access once to fetch wheels.
# Produces: dist\file-organizer.exe (single file).

param(
    [switch]$SkipTests,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
if ($Help) {
    Get-Content $PSCommandPath | Select-Object -Skip 1 -First 10 | ForEach-Object { $_ -replace '^# ?', '' }
    exit 0
}

$root = Split-Path -Parent $PSCommandPath
Set-Location $root

if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements-dev.txt -e .

if (-not $SkipTests) {
    & .\.venv\Scripts\python.exe -m pytest -q
    if ($LASTEXITCODE -ne 0) { Write-Error "tests failed"; exit 1 }
}

& .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm file-organizer.spec
if ($LASTEXITCODE -ne 0) { Write-Error "pyinstaller failed"; exit 1 }

& .\dist\file-organizer.exe --version
if ($LASTEXITCODE -ne 0) { Write-Error "built exe does not run"; exit 1 }
Get-FileHash .\dist\file-organizer.exe -Algorithm SHA256 | Format-List
Write-Host "built dist\file-organizer.exe"
