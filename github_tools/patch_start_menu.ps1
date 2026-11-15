# Always install a Start Menu shortcut to EchoBridge. Desktop shortcut stays optional.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$issPath = Join-Path $project 'release_tools\EchoBridge.iss'
if (-not (Test-Path $issPath)) { throw 'Missing release_tools\EchoBridge.iss' }
$source = [System.IO.File]::ReadAllText($issPath)
$expected = 'Name: "{autoprograms}\EchoBridge\EchoBridge"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"'
# Replace the existing top-level shortcut or an older grouped shortcut.
$pattern = '(?m)^\s*Name:\s*"\{autoprograms\}\\EchoBridge(?:\\EchoBridge)?"\s*;[^\r\n]*'
$shortcutMatches = [regex]::Matches($source, $pattern)
if ($shortcutMatches.Count -gt 1) { throw 'Multiple EchoBridge Start Menu entries found; refusing to create duplicates.' }
if ($shortcutMatches.Count -eq 1) {
    $rule = [regex]::new($pattern)
    $updated = $rule.Replace($source, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $expected }, 1)
} else {
    if ($source -notmatch '(?m)^\[Icons\]\s*$') { throw 'The Inno Setup script has no [Icons] section.' }
    $rule = [regex]::new('(?m)^\[Icons\][ \t]*$')
    $updated = $rule.Replace($source, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) "[Icons]`r`n$expected" }, 1)
}
# Fail fast rather than ever shipping an installer with no Start Menu shortcut.
if (-not $updated.Contains($expected)) { throw 'Could not enforce EchoBridge Start Menu shortcut.' }
if ($updated -ne $source) {
    [System.IO.File]::WriteAllText($issPath, $updated, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'Start Menu shortcut configured: Start > EchoBridge > EchoBridge' -ForegroundColor Green
} else {
    Write-Host 'Start Menu shortcut already configured.' -ForegroundColor Green
}
