"""Offline sanity checks for EchoBridge user-friendly Windows installer features."""
import ast
import importlib.util
import pathlib
import sys
import types

project = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
for name in ('app.py', 'echobridge_model_ui.py', 'echobridge_onboarding.py', 'echobridge_autostart.py'):
    content = (project / name).read_text(encoding='utf-8-sig')
    ast.parse(content, filename=name)

app = (project / 'app.py').read_text(encoding='utf-8-sig')
onboard = (project / 'echobridge_onboarding.py').read_text(encoding='utf-8-sig')
model_ui = (project / 'echobridge_model_ui.py').read_text(encoding='utf-8-sig')
assert 'ECHOBRIDGE_EASY_INSTALL_V1' in app
assert 'set_autostart(bool(checked))' in app
assert 'autostart_enabled()' in app
assert "QTimer.singleShot(0, self.start_install)" in onboard
assert "--bundle" in onboard
assert "def _finished(self, success, message):" in onboard
assert 'taskCompleted.emit(success)' in model_ui
assert 'Remove selected speech model' in model_ui

modspec = importlib.util.spec_from_file_location('echobridge_autostart', project / 'echobridge_autostart.py')
module = importlib.util.module_from_spec(modspec)
modspec.loader.exec_module(module)
assert module.startup_command(r'C:\Program Files\EchoBridge\EchoBridge.exe').startswith('\"')
assert module.startup_command(r'C:\Program Files\EchoBridge\EchoBridge.exe').endswith('\"')
assert module.installed_executable() is None or sys.platform == 'win32'

iss = (pathlib.Path(__file__).with_name('EchoBridge.iss')).read_text(encoding='utf-8')
assert 'Name: "autostart"' in iss
assert 'RegDeleteValue(HKCU, RunKey, RunValue)' in iss
assert 'RegWriteStringValue(HKCU, RunKey, RunValue, ExeCommand)' in iss
assert 'Flags: nowait postinstall skipifsilent' in iss
print('PASS: one-click first-run setup, Windows autostart, installer integration, Python syntax')
