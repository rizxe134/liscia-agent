# Build dist\Liscia-Agent-<ver>-windows-x64.zip (Liscia Agent.exe + its folder, Python bundled). Run in PowerShell on Windows.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$ver = if ($env:VERSION) { $env:VERSION } else { "1.3.0" }
python -m pip install -q -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean liscia_agent.spec
Compress-Archive -Force -Path "dist\Liscia Agent" -DestinationPath "dist\Liscia-Agent-$ver-windows-x64.zip"
Write-Host "Built dist\Liscia-Agent-$ver-windows-x64.zip"
