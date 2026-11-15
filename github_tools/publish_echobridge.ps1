param(
    [switch]$BumpPatch,
    [switch]$CodeOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($BumpPatch -and $CodeOnly) {
    throw 'Choose -BumpPatch for a versioned release OR -CodeOnly for a source-only push.'
}

$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $project
if (-not (Test-Path 'app.py') -or -not (Test-Path 'VERSION.txt') -or -not (Test-Path 'release_tools\EchoBridge.iss')) {
    throw 'Run this from the real EchoBridge project: app.py, VERSION.txt and release_tools\EchoBridge.iss are required.'
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git is missing. Install it with: winget install --id Git.Git --exact'
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI is missing. Install it with: winget install --id GitHub.cli --exact; then reopen PowerShell.'
}

Write-Host '[1/6] Checking GitHub login ...' -ForegroundColor Cyan
try { & gh auth status 2>$null | Out-Null } catch {}
if ($LASTEXITCODE -ne 0) {
    & gh auth login --web --scopes 'repo,workflow'
    if ($LASTEXITCODE -ne 0) { throw 'GitHub login was not completed.' }
}
& gh auth setup-git
if ($LASTEXITCODE -ne 0) { throw 'GitHub Git authentication setup failed.' }
$login = (& gh api user --jq '.login' | Select-Object -First 1).Trim()
if (-not $login) { throw 'Could not determine GitHub username.' }

if (-not (Test-Path '.git')) {
    & git init -b main
    if ($LASTEXITCODE -ne 0) { throw 'Git init failed.' }
}

$gitName = (& git config user.name | Out-String).Trim()
if (-not $gitName) {
    $gitName = $login
    & git config --local user.name $gitName
}
$gitEmail = (& git config user.email | Out-String).Trim()
if (-not $gitEmail) {
    $userId = (& gh api user --jq '.id' | Select-Object -First 1).Trim()
    & git config --local user.email ("{0}+{1}@users.noreply.github.com" -f $userId, $login)
}

$version = (Get-Content 'VERSION.txt' -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "VERSION.txt must contain X.Y.Z. Actual: $version" }

if ($BumpPatch) {
    Write-Host '[2/6] Incrementing version ...' -ForegroundColor Cyan
    $parts = $version.Split('.')
    $newVersion = '{0}.{1}.{2}' -f $parts[0], $parts[1], ([int]$parts[2] + 1)
    $issPath = 'release_tools\EchoBridge.iss'
    $buildPath = 'release_tools\build_release.ps1'
    $iss = Get-Content $issPath -Raw
    $build = Get-Content $buildPath -Raw
    if (-not $iss.Contains(('MyAppVersion "{0}"' -f $version))) {
        throw 'Inno Setup version has drifted; refusing to bump version automatically.'
    }
    if (-not $build.Contains(("EchoBridge-Setup-{0}.exe" -f $version))) {
        throw 'Build script version has drifted; refusing to bump version automatically.'
    }
    $iss = $iss.Replace(('MyAppVersion "{0}"' -f $version), ('MyAppVersion "{0}"' -f $newVersion))
    $build = $build.Replace(("EchoBridge-Setup-{0}.exe" -f $version), ("EchoBridge-Setup-{0}.exe" -f $newVersion))
    Set-Content -Path $issPath -Value $iss -Encoding UTF8 -NoNewline
    Set-Content -Path $buildPath -Value $build -Encoding UTF8 -NoNewline
    Set-Content -Path 'VERSION.txt' -Value $newVersion -Encoding Ascii
    if (Test-Path 'release_tools\README.txt') {
        $info = Get-Content 'release_tools\README.txt' -Raw
        Set-Content 'release_tools\README.txt' -Value ($info.Replace($version,$newVersion)) -Encoding UTF8 -NoNewline
    }
    if (Test-Path 'CHANGELOG.md') {
        $changelog = Get-Content 'CHANGELOG.md' -Raw
        $changelog = $changelog.Replace('# Changelog', "# Changelog`r`n`r`n## [$newVersion] — Maintenance release`r`n`r`n- Updated EchoBridge Windows build and release.`r`n")
        Set-Content 'CHANGELOG.md' -Value $changelog -Encoding UTF8 -NoNewline
    }
    $version = $newVersion
    Write-Host "  New release: v$version" -ForegroundColor Green
}

$remotes = @(& git remote)
$remoteUrl = ''
if ($remotes -contains 'origin') {
    $remoteUrl = (& git remote get-url origin | Out-String).Trim()
}
if ($remoteUrl) {
    $repoName = (& gh repo view --json name --jq '.name' | Select-Object -First 1).Trim()
    if ($repoName -ne 'EchoBridge') {
        throw "The existing origin does not point to a repo called EchoBridge (found: $repoName). No push attempted."
    }
    $slug = (& gh repo view --json nameWithOwner --jq '.nameWithOwner' | Select-Object -First 1).Trim()
} else {
    $slug = "$login/EchoBridge"
}
$repoUrl = "https://github.com/$slug"

$marker = Join-Path $PSScriptRoot '.initialized'
# A GitHub clone already contains the published docs/workflows; do not overwrite
# them with the starter templates merely because the local marker is absent.
$alreadyPublished = (Test-Path 'LICENSE') -and (Test-Path '.github\workflows\release.yml') -and (Test-Path 'README.md')
if (-not (Test-Path $marker) -and -not $alreadyPublished) {
    Write-Host '[2/6] Preparing README, MIT license, GitHub files ...' -ForegroundColor Cyan
    $templateRoot = Join-Path $PSScriptRoot 'templates'
    if (-not (Test-Path $templateRoot)) {
        throw 'GitHub templates are missing. Extract the full publishing kit again.'
    }
    $backupRoot = Join-Path $project '.github-publisher-backups'
    $stamped = Join-Path $backupRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
    foreach ($source in @(Get-ChildItem $templateRoot -Recurse -File)) {
        $relative = $source.FullName.Substring($templateRoot.Length + 1)
        $destination = Join-Path $project $relative
        $folder = Split-Path $destination -Parent
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
        if (Test-Path $destination) {
            $backupTarget = Join-Path $stamped $relative
            New-Item -ItemType Directory -Force -Path (Split-Path $backupTarget -Parent) | Out-Null
            Copy-Item $destination $backupTarget -Force
        }
        $contents = Get-Content $source.FullName -Raw -Encoding UTF8
        $contents = $contents.Replace('__REPO_URL__', $repoUrl)
        $contents = $contents.Replace('__VERSION__', $version)
        $contents = $contents.Replace('__COPYRIGHT_HOLDER__', $gitName)
        # Always UTF-8 without BOM (important for LICENSE and YAML).
        [System.IO.File]::WriteAllText($destination, $contents, (New-Object System.Text.UTF8Encoding($false)))
    }
    New-Item -ItemType File -Path $marker -Force | Out-Null
}

# Make the installed app easy to find in the Windows Start menu.
Write-Host 'Configuring Start Menu shortcut ...' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'patch_start_menu.ps1')
if (-not $?) { throw 'Start Menu shortcut patch failed.' }

# Avoid launching Explorer inside noninteractive GitHub Actions runners.
$buildFile = 'release_tools\build_release.ps1'
$buildSource = Get-Content $buildFile -Raw
$explorerLine = 'Start-Process explorer.exe -ArgumentList @((Join-Path $project ''releases''))'
if ($buildSource.Contains($explorerLine) -and -not $buildSource.Contains('if (-not $env:CI) { ' + $explorerLine)) {
    $buildSource = $buildSource.Replace($explorerLine, 'if (-not $env:CI) { ' + $explorerLine + ' }')
    [System.IO.File]::WriteAllText((Join-Path $project $buildFile), $buildSource, (New-Object System.Text.UTF8Encoding($false)))
}

# Stage only known EchoBridge source, documentation and release automation.
# Do not sweep random files from the developer's machine into a public repo.
Write-Host '[3/6] Staging safe source files ...' -ForegroundColor Cyan
$sourcePaths = @(
    'app.py', 'VERSION.txt', 'requirements.txt', 'pytest.ini',
    'README.md', 'LICENSE', 'CHANGELOG.md', 'CONTRIBUTING.md', 'SECURITY.md',
    '.gitignore', '.gitattributes', 'build_windows.ps1',
    'release_tools', 'tests', '.github', 'docs', 'assets',
    'github_tools/publish_echobridge.ps1', 'github_tools/patch_start_menu.ps1'
)
$sourcePaths += @(Get-ChildItem -File -Filter '*.py' | ForEach-Object { $_.Name })
$present = @($sourcePaths | Where-Object { Test-Path $_ } | Select-Object -Unique)
& git add -A -- $present
if ($LASTEXITCODE -ne 0) { throw 'Git add failed.' }
# Include deletions of files already tracked in older EchoBridge commits.
& git add -u
if ($LASTEXITCODE -ne 0) { throw 'Git update-index failed.' }
$staged = @(& git diff --cached --name-only)
$unsafe = @($staged | Where-Object {
    $_ -match '(^|/)(\.venv|venv|dist|build|releases|runtimes|models|recordings|logs)(/|$)' -or
    $_ -match '(^|/)(\.env(\.|$)|secrets\.json$|credentials\.json$|token\.json$|api_keys\.json$)' -or
    $_ -match '\.(gguf|wav|mp3|pfx|pem|key|exe|dll|zip)$'
})
if ($unsafe.Count -gt 0) {
    & git reset --quiet
    throw ("Found private/generated files in Git staging. Aborted: " + ($unsafe -join ', '))
}
Write-Host '  Staged files:' -ForegroundColor DarkCyan
$staged | ForEach-Object { Write-Host ('    ' + $_) }

# Make a commit if the repository has changes.
& git diff --cached --quiet
if ($LASTEXITCODE -eq 1) {
    & git commit -m "Prepare EchoBridge $version for GitHub publishing"
    if ($LASTEXITCODE -ne 0) { throw 'Git commit failed.' }
} elseif ($LASTEXITCODE -ne 0) {
    throw 'Git diff failed.'
} else {
    Write-Host '  No new source changes to commit.'
}

Write-Host '[4/6] Creating or updating the public EchoBridge repository ...' -ForegroundColor Cyan
$branch = (& git branch --show-current | Select-Object -First 1).Trim()
if (-not $branch) { throw 'Git has no active branch.' }
if (-not $remoteUrl) {
    $exists = ''
    try { $exists = (& gh repo view $slug --json nameWithOwner --jq '.nameWithOwner' 2>$null | Out-String).Trim() } catch { $exists = '' }
    if (-not $exists) {
        & gh repo create EchoBridge --public --source . --remote origin --description 'EchoBridge — offline push-to-talk speech transcription and translation for Windows'
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the GitHub repository.' }
    } else {
        & git remote add origin "https://github.com/$slug.git"
        if ($LASTEXITCODE -ne 0) { throw 'Could not attach existing GitHub repository.' }
    }
}
& git push --set-upstream origin $branch
if ($LASTEXITCODE -ne 0) { throw 'Git push failed. Source was not published.' }

if ($CodeOnly) {
    Write-Host "Source pushed: $repoUrl" -ForegroundColor Green
    exit 0
}

Write-Host '[5/6] Publishing version tag ...' -ForegroundColor Cyan
$tag = "v$version"
$remoteTag = (& git ls-remote --tags origin "refs/tags/$tag" | Out-String).Trim()
$localTag = (& git tag --list $tag | Out-String).Trim()
if ($remoteTag) {
    Write-Host "  Tag $tag already exists remotely; not overwriting it." -ForegroundColor Yellow
    Write-Host '  For the next release, use: .\github_tools\publish_echobridge.ps1 -BumpPatch'
} else {
    if ($localTag) {
        $tagCommit = (& git rev-list -n 1 $tag | Select-Object -First 1).Trim()
        $headCommit = (& git rev-parse HEAD | Select-Object -First 1).Trim()
        if ($tagCommit -ne $headCommit) { throw "Existing local $tag points to an older commit. Refusing to move it." }
    } else {
        & git tag -a $tag -m "EchoBridge $version"
        if ($LASTEXITCODE -ne 0) { throw 'Could not create version tag.' }
    }
    & git push origin $tag
    if ($LASTEXITCODE -ne 0) { throw 'Could not push release tag.' }
}

Write-Host '[6/6] GitHub Actions will now build the Windows installer and publish it under Releases.' -ForegroundColor Green
Write-Host "Repository: $repoUrl" -ForegroundColor Cyan
Write-Host "Build progress: $repoUrl/actions" -ForegroundColor Cyan
Write-Host "Release downloads: $repoUrl/releases" -ForegroundColor Cyan
& gh repo view --web
