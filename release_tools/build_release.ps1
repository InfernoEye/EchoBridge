# Compile the EXACT working source tree in place, without modifying its Python files.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $project
$py = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw 'Project virtual environment missing: .venv\Scripts\python.exe' }
if (-not (Test-Path 'app.py')) { throw 'app.py not found. Put release_tools inside the working EchoBridge project.' }
if (-not (Test-Path 'echobridge_worker.py')) { throw 'echobridge_worker.py missing.' }
if (-not (Test-Path 'echobridge_setup.py')) { throw 'echobridge_setup.py missing.' }

Write-Host '[0/7] Enabling one-click setup and Windows autostart controls ...' -ForegroundColor Cyan
& $py (Join-Path $PSScriptRoot 'patch_easy_installer.py') --project $project
if ($LASTEXITCODE -ne 0) { throw 'Could not safely integrate easy installer features. Existing files were not overwritten.' }
& $py (Join-Path $PSScriptRoot 'verify_easy_installer.py') $project
if ($LASTEXITCODE -ne 0) { throw 'Easy installer checks failed.' }

Write-Host '[1/7] Installing Windows build tools ...' -ForegroundColor Cyan
& $py -m pip install --disable-pip-version-check 'pyinstaller>=6,<7' 'pillow>=10,<13'
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }

Write-Host '[2/7] Checking source and tests ...' -ForegroundColor Cyan
& $py -m compileall -q -x '\\.venv\\|\\build\\|\\dist\\' app.py echobridge_worker.py echobridge_setup.py
if ($LASTEXITCODE -ne 0) { throw 'Python compilation failed.' }
if (Test-Path 'tests') {
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Project tests failed. No installer created.' }
}

Write-Host '[3/7] Generating app icon ...' -ForegroundColor Cyan
$icon = Join-Path $PSScriptRoot 'echobridge.ico'
& $py (Join-Path $PSScriptRoot 'make_icon.py') $icon
if ($LASTEXITCODE -ne 0) { throw 'Icon creation failed.' }

Write-Host '[4/7] Building portable EchoBridge.exe ...' -ForegroundColor Cyan
$hidden = @(
    'echobridge_worker', 'echobridge_setup', 'echobridge_models',
    'echobridge_model_ui', 'echobridge_audio_quality',
    'echobridge_transcription', 'echobridge_translation_routes',
    'echobridge_languages', 'echobridge_onboarding', 'echobridge_preload',
    'echobridge_server_client', 'echobridge_gpus', 'echobridge_microphones',
    'echobridge_capture', 'echobridge_hotkey', 'echobridge_priority',
    'echobridge_runtime', 'echobridge_autostart', 'echobridge_tasks',
    'echobridge_translation_ui'
)
$argList = @(
    '--noconfirm', '--clean', '--onedir', '--windowed',
    '--name', 'EchoBridge', '--icon', $icon,
    '--runtime-hook', (Join-Path $PSScriptRoot 'frozen_stdio.py'),
    '--distpath', (Join-Path $project 'dist'),
    '--workpath', (Join-Path $project 'build'),
    '--specpath', (Join-Path $project 'build')
)
foreach ($module in $hidden) {
    if (Test-Path (Join-Path $project ($module + '.py'))) {
        $argList += @('--hidden-import', $module)
    }
}
# Collect dynamic Python/native dependencies of Argos and audio capture.
foreach ($module in @('argostranslate', 'stanza', 'ctranslate2', 'sentencepiece', 'sounddevice', 'scipy', 'numpy', 'certifi')) {
    & $py -c 'import importlib.util,sys; sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)' $module
    if ($LASTEXITCODE -eq 0) { $argList += @('--collect-all', $module) }
}
$argList += 'app.py'
& $py -m PyInstaller @argList
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
$exe = Join-Path $project 'dist\EchoBridge\EchoBridge.exe'
if (-not (Test-Path $exe)) { throw 'EchoBridge.exe was not produced.' }

Write-Host '[5/7] Smoke-testing frozen worker/setup output ...' -ForegroundColor Cyan
# Check that the windowed exe still has stdin/stdout attached when called
# by EchoBridge's QProcess worker. A broken worker would silently fail.
foreach ($mode in @('--worker', '--setup')) {
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo.FileName = $exe
    $proc.StartInfo.Arguments = "$mode --help"
    $proc.StartInfo.UseShellExecute = $false
    $proc.StartInfo.CreateNoWindow = $true
    $proc.StartInfo.RedirectStandardInput = $true
    $proc.StartInfo.RedirectStandardOutput = $true
    $proc.StartInfo.RedirectStandardError = $true
    [void]$proc.Start()
    # The smoke test passes --help, so no input is expected. Closing the pipe
    # also prevents an accidental read from waiting indefinitely for input.
    $proc.StandardInput.Close()
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    if (-not $proc.WaitForExit(30000)) {
        try { $proc.Kill() } catch {}
        throw "$mode frozen-process smoke test timed out."
    }
    if ($proc.ExitCode -ne 0 -or $stdout -notmatch 'usage:') {
        throw "$mode frozen-process smoke test failed (exit $($proc.ExitCode)): $stderr $stdout"
    }
    $proc.Dispose()
}
Write-Host '  Portable build OK.' -ForegroundColor Green

Write-Host '[6/7] Building normal Windows setup installer ...' -ForegroundColor Cyan
$compiler = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $compiler) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Inno Setup is required for the installer. Install it from https://jrsoftware.org/isdl.php. Portable EXE is already built.'
    }
    & winget install --id JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup installation failed. Portable EXE is already built.' }
    $compiler = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $compiler) { throw 'Could not locate ISCC.exe. Portable EXE is already built.' }
& $compiler (Join-Path $PSScriptRoot 'EchoBridge.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed. Portable EXE is already built.' }
$setup = Join-Path $project 'releases\EchoBridge-Setup-0.5.1.exe'
if (-not (Test-Path $setup)) { throw 'Installer output missing.' }
Write-Host ''
Write-Host 'SUCCESS! EchoBridge installer:' -ForegroundColor Green
Write-Host $setup -ForegroundColor Green
Write-Host 'Portable executable (keep _internal folder with it):' -ForegroundColor Green
Write-Host $exe -ForegroundColor Green
Write-Host 'New users: install the single EXE, launch, choose microphone and languages, then Install & Continue.' -ForegroundColor Cyan
Write-Host 'Autostart is optional during installation and adjustable later in Settings.' -ForegroundColor Cyan
if (-not $env:CI) { Start-Process explorer.exe -ArgumentList @((Join-Path $project 'releases')) }
