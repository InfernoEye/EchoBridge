# Contributing to EchoBridge

Thanks for helping EchoBridge improve. Windows is the first supported platform; Linux support is a future milestone.

## Report a bug

Search existing issues before opening one. Include your Windows version, microphone type, CPU/GPU, Whisper model, source/target languages, steps to reproduce and expected versus actual behavior. Do not upload private recordings or raw logs containing sensitive data.

## Develop locally

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe app.py
```

Prefer small pull requests with tests. Keep capture behavior independent of model initialization and preserve the user-visible instant-capture privacy disclosure.

## Releases

The owner publishes a new version by updating `VERSION.txt`, the Inno Setup version, and the build script's expected output name, then pushing a matching `vX.Y.Z` tag. The provided `github_tools/publish_echobridge.ps1 -BumpPatch` command handles this automatically after initial setup. GitHub Actions tests, builds, and attaches the Windows installer and portable ZIP to the versioned release.

Don't commit virtual environments, generated binaries, local history, logs, secrets, downloaded runtimes or AI models.
