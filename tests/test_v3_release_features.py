"""Offline integration checks for V3. Hardware tests run on Windows."""
from pathlib import Path
import ast

from echobridge_server_client import parse_server_result, windows_process_alive

ROOT = Path(__file__).resolve().parents[1]


def content(name):
    value = (ROOT / name).read_text(encoding='utf-8')
    ast.parse(value)
    return value


def test_preloader_starts_during_key_press_after_recording():
    src = content('echobridge_runtime.py')
    tree = ast.parse(src)
    runtime = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'EchoBridgeRuntime')
    press = next(n for n in runtime.body if isinstance(n, ast.FunctionDef) and n.name == 'on_pressed')
    snippet = ast.get_source_segment(src, press)
    assert snippet.index('self.recorder.start(') < snippet.index('self.start_preload()')
    assert 'self.probe_timer.start()' in src
    assert 'self.preload_ready = True' in src
    assert 'preload_error' in src
    assert '--warm-pid' in src


def test_worker_can_abort_fallback_when_server_exits():
    code = content('echobridge_worker.py')
    assert 'transcribe_preloaded(' in code
    assert 'args.warm_pid' in code
    assert 'Preload failed' in code
    assert windows_process_alive(None) is True


def test_translation_settings_are_separate_from_models():
    model = content('echobridge_model_ui.py')
    translator = content('echobridge_translation_ui.py')
    app = content('app.py')
    assert 'Offline translation packages' not in model
    assert 'Installed language packages' in translator
    assert 'source' in translator and 'target' in translator
    assert 'root.addTab(self.translation, "Translations")' in app
    assert 'root.addTab(self.ai_models, "AI Models")' in app


def test_uninstall_actions_require_exact_selected_targets():
    setup = content('echobridge_setup.py')
    assert "action.add_argument('--remove-model'" in setup
    assert "action.add_argument('--remove-runtime'" in setup
    assert "action.add_argument('--remove-vad'" in setup
    assert "action.add_argument('--remove-pair'" in setup
    assert 'pkg.uninstall(matching[0])' in setup
    assert "dest = model_path(name)" in setup
    assert "if backend not in ('cpu', 'gpu')" in setup


def test_first_run_installs_all_four_components():
    setup = content('echobridge_setup.py')
    onboarding = content('echobridge_onboarding.py')
    assert "('Speech model', lambda: install_model(name)" in setup
    assert "('Speech detector', install_vad, vad_ready)" in setup
    assert "('Whisper runtime', lambda: install_runtime(backend)" in setup
    assert 'lambda: install_pair(source, target)' in setup
    assert "['--bundle', device, model_name(), source, target]" in onboarding
    assert 'self.job.progress.connect(self._progress)' in onboarding
    assert 'onboarding_completed_v3' in onboarding


def test_transcription_result_parser_preserves_manual_language():
    text, source = parse_server_result({'text': 'Jak się dzisiaj czujesz?', 'language': 'English'}, 'pl')
    assert source == 'pl'
    assert text == 'Jak się dzisiaj czujesz?'


def test_release_can_package_new_pages():
    build = (ROOT / 'release_tools' / 'build_release.ps1').read_text()
    assert "'echobridge_translation_ui'" in build
    assert "'echobridge_tasks'" in build
    assert 'EchoBridge-Setup-0.5.1.exe' in build
