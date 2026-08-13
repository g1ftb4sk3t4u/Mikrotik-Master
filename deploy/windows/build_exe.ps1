# Builds a standalone Windows executable (dist\mikrotik-grabber.exe) with PyInstaller.
# The resulting exe bundles Python + all dependencies, so it runs on a machine
# without Python installed. Double-clicking it launches the GUI; run from a
# terminal with subcommands (scan/watch) for headless use.

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

pyinstaller --noconfirm --clean `
    --name mikrotik-grabber `
    --onefile `
    --collect-all sv_ttk `
    run.py

Write-Host ""
Write-Host "Build complete: $repoRoot\dist\mikrotik-grabber.exe"
Write-Host "GUI:      .\dist\mikrotik-grabber.exe"
Write-Host "Headless: .\dist\mikrotik-grabber.exe scan --output D:\mikrotik_archive"
