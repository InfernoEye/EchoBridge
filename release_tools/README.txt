EchoBridge 0.5.1 — Windows installer build

Developer: open PowerShell in the extracted clean V3 source directory.

  py -3.11 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  .\.venv\Scripts\python.exe -m pytest -q
  powershell -NoProfile -ExecutionPolicy Bypass -File .\release_tools\build_release.ps1

Success outputs:
  releases\EchoBridge-Setup-0.5.1.exe (installer)
  dist\EchoBridge\EchoBridge.exe (portable; keep _internal folder alongside)

The setup installer is a single EXE for end users. The first launch presents
an in-app setup wizard to select microphone, languages, processor, Whisper
model, and hotkey, then download runtime, speech model, VAD and translation
packages with explicit progress. These are downloaded during first-run setup,
not when pressing F8. Automatic language detection requires a principal offline
translation source selected at setup; more pairs can be installed later in
Settings > Translations.

Windows autostart is optional in the installer, and can be changed later
under Settings > General.

IMPORTANT: The app is unsigned and may trigger Windows SmartScreen warnings.
Test the built EXE and installer on a fresh Windows computer, including the
microphone, the Whisper preloaded server, model downloads, worker pipes and
AMD/NVIDIA GPU runtime options before public distribution.
