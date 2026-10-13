# Build dist\PC-Agent-<ver>-windows-x64.zip (PC Agent.exe + its folder, Python bundled). Run in PowerShell on Windows.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$ver = if ($env:VERSION) { $env:VERSION } else { "1.0.0" }
python -m pip install -q -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean pc_agent.spec
Compress-Archive -Force -Path "dist\PC Agent" -DestinationPath "dist\PC-Agent-$ver-windows-x64.zip"
Write-Host "Built dist\PC-Agent-$ver-windows-x64.zip"
