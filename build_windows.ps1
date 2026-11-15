# Unified build entry point for EchoBridge 0.5.0.
# Build the installer and the portable distribution with frozen subprocess support.
$ErrorActionPreference = 'Stop'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'release_tools\build_release.ps1')
if ($LASTEXITCODE -ne 0) { throw 'EchoBridge Windows build failed.' }
