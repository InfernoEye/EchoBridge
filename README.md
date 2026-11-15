# EchoBridge

**Speak naturally. Translate locally. Keep working.**

EchoBridge is a **Windows-first, open-source desktop app** for push-to-talk speech transcription and offline translation. Hold a configurable shortcut (F8 by default), speak, then release it. EchoBridge shows your original words and their translation in a small, always-on-top popup designed not to interrupt your current application.

[**Download EchoBridge for Windows**](https://github.com/InfernoEye/EchoBridge/releases) · [Report an issue](https://github.com/InfernoEye/EchoBridge/issues) · [Contributing guide](CONTRIBUTING.md)

> **Status:** Early release (v0.5.1). Windows is the current development priority; Linux support is planned. Please report hardware-specific issues.

## Highlights

- **Hold to record, release to translate** with a configurable global hotkey.
- **Whisper transcription** with automatic or manually selected source language.
- **Offline text translation** using downloadable Argos Translate language packages.
- **Windows CPU, AMD and NVIDIA options** through CPU or compatible Vulkan-based Whisper runtimes. Availability and performance depend on hardware and drivers.
- **Instant Capture** to reduce missed first words. This keeps the microphone stream active while EchoBridge runs, but discards samples unless the hotkey is held.
- **Compact translation popup** with original and translated text, copy buttons, automatic timeout and pause-on-hover.
- **First-run setup wizard** for choosing your microphone, language pair, runtime and model and downloading required components.
- **System tray** controls for Settings, recent translations and Quit.
- **Optional Start with Windows** toggle in the installer and app settings.
- **On-demand AI inference:** Whisper models are released from RAM/VRAM after each task and cached on disk for later use.

## Install on Windows

1. Open [GitHub Releases](https://github.com/InfernoEye/EchoBridge/releases).
2. Download the newest **`EchoBridge-Setup-*.exe`** file.
3. Run the installer, and optionally choose **Start EchoBridge with Windows**. The installer automatically creates a **Start → EchoBridge → EchoBridge** shortcut; a desktop shortcut is optional.
4. Launch EchoBridge. On first run, select a microphone, speech language (or Automatic), translation language, and the recommended CPU option or a supported GPU.
5. Click **Install & Continue** in the setup wizard. It downloads the required Whisper runtime, selected model, speech detector and translation packages. This step needs internet access. Subsequent transcription and installed language-pair translation work locally.
6. Hold **F8**, speak, and release it to see the result.

> On some Windows systems, an unsigned installer may trigger SmartScreen. This project does **not** claim Microsoft code-signing certification. Download only from this repository's Releases page and check the release notes.

### Portable option

`EchoBridge-Windows-Portable-*.zip` contains `EchoBridge.exe` and its required companion files. Extract **the complete archive** before launching; the EXE alone is not a standalone portable build. Model downloads are still needed on first launch.

## Settings

| Section | Options |
|---|---|
| **General** | Global hotkey, active microphone, live microphone test, Instant Capture, popup timeout, Windows autostart |
| **Translations** | Spoken language (Automatic or fixed), translation target, downloadable language packages and removal |
| **AI Models** | CPU/AMD/NVIDIA processing choice, named GPU selection, Whisper model and runtime download/removal |

### Microphone and privacy

**Instant Capture** favors responsiveness: Windows may show your microphone as *in use* while EchoBridge is running, even when you are not holding F8. EchoBridge discards those idle samples and does not save or submit them for transcription. Disable Instant Capture under **Settings → General** if you want a microphone stream that is stopped between recordings. See [Privacy](docs/PRIVACY.md).

Speech and translation are processed locally after the required components are downloaded. Your computer may still contact download servers during initial setup. Recent translation history is stored locally by the application, so avoid speaking sensitive information if you do not want it retained in that history.

## Troubleshooting

- **Missing beginning of a sentence:** Enable Instant Capture, verify the right microphone is selected, and test its input meter. Recording begins when the hotkey is pressed; model loading is a separate operation.
- **Transcription detects the wrong language:** Select a fixed source language under **Translations** and try again. Very short clips are harder to auto-detect.
- **Slow first transcription:** Larger Whisper models take longer to load. Use a smaller model or GPU when supported. The model is unloaded after a task by design.
- **GPU runtime fails:** Try **CPU** first, update graphics drivers, and use **AI Models** to verify installation. GPU availability varies by device.
- **Translation missing:** Open **Translations** and install the package for your selected source-to-target pair.
- **No recording:** Allow microphone access for desktop apps in Windows privacy settings, then use the in-app microphone test.
- **Detailed logs:** Check `%LOCALAPPDATA%\EchoBridge\logs\application.log`, where available, and remove sensitive data before submitting logs to an issue.

## Build from source (Windows)

Requirements: **Python 3.11**, PowerShell, and Inno Setup 6/7 for installers.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe app.py
```

Create an installer locally:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\release_tools\build_release.ps1
```

Output: `releases\EchoBridge-Setup-0.5.1.exe` and `dist\EchoBridge\` (portable folder).

### Automatic GitHub releases

The repository includes a GitHub Actions pipeline. A push of a version tag such as `v0.5.1` runs the Windows tests and installer build, then publishes the installer and portable ZIP under [Releases](https://github.com/InfernoEye/EchoBridge/releases). See [Contributing](CONTRIBUTING.md) for publishing instructions. Generated binaries and large model files are not committed to Git.

## Contributing

Bug reports, documentation improvements and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md). For security problems, see [SECURITY.md](SECURITY.md).

## License

EchoBridge's **own source code** is licensed under the [MIT License](LICENSE). Its dependencies, downloaded Whisper models, translation packages and third-party runtimes are covered by their respective licenses; distributing EchoBridge does not change those licenses.
