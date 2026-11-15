"""Idempotently add a login toggle and a one-click guided AI setup to V2.

Uses structural markers rather than file hashes to avoid patch-version mismatch.
Writes backups and validates every file before changing the project.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import shutil
import sys


def replace_once(src, old, new, label):
    if old not in src:
        raise RuntimeError(f'{label}: expected source marker missing; source left unchanged')
    if src.count(old) != 1:
        raise RuntimeError(f'{label}: source marker repeated; source left unchanged')
    return src.replace(old, new, 1)


def patch(project, kit):
    files = {name: project / name for name in ('app.py', 'echobridge_onboarding.py', 'echobridge_model_ui.py')}
    for path in files.values():
        if not path.is_file():
            raise RuntimeError(f'Missing source: {path}')
    content = {name: path.read_text(encoding='utf-8-sig') for name, path in files.items()}
    if 'ECHOBRIDGE_EASY_INSTALL_V1' in content['app.py']:
        print('Easy installer features already installed; no changes required.')
        return

    app = content['app.py']
    app = replace_once(app,
        'from echobridge_onboarding import FirstRunWizard\n',
        'from echobridge_onboarding import FirstRunWizard\n'
        'from echobridge_autostart import installed_executable, enabled as autostart_enabled, set_enabled as set_autostart\n',
        'autostart module import')
    # QCheckBox imported as independent explicit line to handle different GUI source variants.
    app = replace_once(app,
        '    QApplication, QComboBox, QDialog, QFrame, QHBoxLayout,\n',
        '    QApplication, QComboBox, QCheckBox, QDialog, QFrame, QHBoxLayout,\n',
        'QCheckBox import')
    app = replace_once(app,
        '        layout.addWidget(subtitle)\n',
        '''        layout.addWidget(subtitle)

        # ECHOBRIDGE_EASY_INSTALL_V1
        layout.addWidget(self.heading("Windows Startup"))
        self.autostart_toggle = QCheckBox("Start EchoBridge when I sign in to Windows")
        self.autostart_toggle.setChecked(autostart_enabled())
        self.autostart_toggle.setEnabled(installed_executable() is not None)
        self.autostart_toggle.toggled.connect(self.change_autostart)
        layout.addWidget(self.autostart_toggle)
        self.autostart_description = QLabel(
            "EchoBridge starts quietly in the tray. You can change this anytime."
            if installed_executable() is not None else
            "Autostart becomes available in the installed Windows application."
        )
        self.autostart_description.setWordWrap(True)
        self.autostart_description.setObjectName("muted")
        layout.addWidget(self.autostart_description)
''',
        'startup checkbox')
    # Refresh on show: installation choices may have been set after Settings was constructed.
    app = replace_once(app,
        '''    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_microphones()
''',
        '''    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_microphones()
        if hasattr(self, 'autostart_toggle'):
            self.autostart_toggle.blockSignals(True)
            self.autostart_toggle.setChecked(autostart_enabled())
            self.autostart_toggle.blockSignals(False)

    def change_autostart(self, checked):
        from PySide6.QtWidgets import QMessageBox
        try:
            set_autostart(bool(checked))
        except (RuntimeError, OSError, PermissionError) as exc:
            self.autostart_toggle.blockSignals(True)
            self.autostart_toggle.setChecked(autostart_enabled())
            self.autostart_toggle.blockSignals(False)
            QMessageBox.warning(self, "EchoBridge — Windows startup", str(exc))
''',
        'refresh startup checkbox')

    model_ui = content['echobridge_model_ui.py']
    model_ui = replace_once(model_ui,
        'from PySide6.QtCore import QProcess, QSettings, QSignalBlocker, QTimer\n',
        'from PySide6.QtCore import QProcess, QSettings, QSignalBlocker, QTimer, Signal\n',
        'model ui Signal import')
    model_ui = replace_once(model_ui,
        'class ModelSettingsPage(QWidget):\n',
        'class ModelSettingsPage(QWidget):\n    taskCompleted = Signal(bool)\n',
        'model ui completion signal')
    model_ui = replace_once(model_ui,
        '''        if success:
            # Do not modify source or target. Refresh actual on-disk package and runtime status.
            self.refresh()
            QMessageBox.information(self, 'EchoBridge', f'{self.task_description} finished.\\n\\n{self.status.text()}')
        else:
            QMessageBox.warning(self, 'EchoBridge', self.status.text())
''',
        '''        if success:
            # Do not modify source or target. Refresh actual on-disk package and runtime status.
            self.refresh()
        if not getattr(self, 'batch_mode', False):
            if success:
                QMessageBox.information(self, 'EchoBridge', f'{self.task_description} finished.\\n\\n{self.status.text()}')
            else:
                QMessageBox.warning(self, 'EchoBridge', self.status.text())
        self.taskCompleted.emit(success)
''',
        'model ui batch completion')

    onboarding = content['echobridge_onboarding.py']
    onboarding = replace_once(onboarding,
        '''        self.ai_models = ModelSettingsPage(self)
        self.pages.addWidget(self.ai_models)
''',
        '''        self.ai_models = ModelSettingsPage(self)
        self.ai_models.taskCompleted.connect(self.quick_setup_step_completed)
        self.quick_queue = []
        self.quick_running = False
        self.quick_total = 0
        self.quick_button = QPushButton('Install Recommended Components')
        self.quick_button.setObjectName('primary')
        self.quick_button.clicked.connect(self.start_quick_setup)
        self.quick_info = self.label(
            'One click downloads everything EchoBridge needs for your chosen languages. '
            'Uses CPU by default for compatibility; you can change GPU/model settings below.', True
        )
        self.ai_models.layout().insertWidget(0, self.quick_info)
        self.ai_models.layout().insertWidget(0, self.quick_button)
        self.pages.addWidget(self.ai_models)
''',
        'onboarding quick button')
    onboarding = replace_once(onboarding,
        '''    def go_back(self):
''',
        '''    def start_quick_setup(self):
        """Download offline speech components BEFORE any recording; no silent model downloads."""
        if self.quick_running or self.ai_models.task is not None:
            return
        if not self.store_basics():
            return
        from echobridge_models import model_ready, runtime_path
        from echobridge_preload import find_server
        from echobridge_translation_routes import plan_translation
        from echobridge_models import model_name, device_name

        backend = device_name()
        if backend != 'cpu' and find_server(runtime_path(backend)) is None:
            permission = QMessageBox.question(
                self, 'EchoBridge GPU runtime',
                'GPU acceleration requires an additional third-party Windows Vulkan runtime.\\n'
                'It will be downloaded from a public GitHub release, not from Microsoft or the GPU manufacturer.\\n\\n'
                'Continue with this download?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if permission != QMessageBox.StandardButton.Yes:
                self.quick_info.setText('GPU runtime download not approved. Choose CPU or install GPU runtime manually.')
                return
        source = normalize_speech_language(SETTINGS.value('speech_language', 'auto'))
        target = str(SETTINGS.value('language', 'en') or 'en')
        if source == 'auto':
            source = str(self.ai_models.source.currentData() or 'pl')
        self.ai_models.batch_mode = True
        tasks = []
        if find_server(runtime_path(backend)) is None:
            tasks.append((['--runtime', 'cpu' if backend == 'cpu' else 'gpu'], 'Speech engine runtime'))
        if not model_ready(model_name()):
            tasks.append((['--model', model_name()], 'Whisper speech model'))
        if source != target:
            try:
                import argostranslate.package as pkg
                packages = {(p.from_code, p.to_code) for p in pkg.get_installed_packages()}
                plan_translation(source, target, packages)
            except (ImportError, ValueError, RuntimeError, OSError):
                tasks.append((['--pair', source, target], f'Offline translation {source} → {target}'))
        if not tasks:
            self.quick_info.setText('Everything is already installed. Click Next to finish setup.')
            self.quick_button.setText('Already Installed')
            self.ai_models.batch_mode = False
            self.index = 2
            self.update_step()
            return
        self.quick_queue = tasks
        self.quick_total = len(tasks)
        self.quick_running = True
        self.quick_button.setEnabled(False)
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.later.setEnabled(False)
        self._launch_next_quick_task()

    def _launch_next_quick_task(self):
        if not self.quick_queue:
            self.quick_running = False
            self.ai_models.batch_mode = False
            self.quick_button.setEnabled(True)
            self.later.setEnabled(True)
            self.quick_info.setText('Recommended components are installed.')
            self.index = 2
            self.update_step()
            return
        args, description = self.quick_queue.pop(0)
        step = self.quick_total - len(self.quick_queue)
        self.quick_info.setText(f'Installing {step} of {self.quick_total}: {description}. Keep this window open.')
        self.ai_models.launch(args, description)

    def quick_setup_step_completed(self, success):
        if not self.quick_running:
            return
        if not success:
            self.quick_running = False
            self.quick_queue.clear()
            self.ai_models.batch_mode = False
            self.quick_button.setEnabled(True)
            self.later.setEnabled(True)
            self.quick_info.setText('Installation stopped. Check the error below and retry.')
            self.update_step()
            return
        QTimer.singleShot(0, self._launch_next_quick_task)

    def go_back(self):
''',
        'onboarding quick setup methods')
    onboarding = replace_once(onboarding,
        '''    def update_step(self):
        self.pages.setCurrentIndex(self.index)
''',
        '''    def update_step(self):
        self.pages.setCurrentIndex(self.index)
''',
        'onboarding page state')
    onboarding = replace_once(onboarding,
        '''        self.previous.setEnabled(self.index > 0)
        self.next.setText('Finish setup' if self.index == 2 else 'Next')
''',
        '''        self.previous.setEnabled(self.index > 0 and not self.quick_running)
        self.next.setEnabled(not self.quick_running)
        self.next.setText('Install & Continue' if self.index == 0 else
                          'Finish setup' if self.index == 2 else 'Next')
''',
        'onboarding navigation state')
    onboarding = replace_once(onboarding,
        '''    def go_next(self):
        if self.index == 0 and not self.store_basics():
''',
        '''    def go_next(self):
        if self.quick_running:
            return
        if self.index == 0 and not self.store_basics():
''',
        'onboarding navigation guard')
    onboarding = replace_once(onboarding,
        '''        if self.index < 2:
            self.index += 1
            self.update_step()
        else:
''',
        '''        if self.index < 2:
            self.index += 1
            self.update_step()
            if self.index == 1:
                # Install & Continue is explicit consent to downloading the required components.
                QTimer.singleShot(0, self.start_quick_setup)
        else:
''',
        'onboarding automatic recommended setup')
    onboarding = replace_once(onboarding,
        '''    def go_back(self):
        if self.ai_models.task is not None:
''',
        '''    def go_back(self):
        if self.quick_running:
            return
        if self.ai_models.task is not None:
''',
        'onboarding go back guard')
    onboarding = replace_once(onboarding,
        '''    def reject(self):
        if self.ai_models.task is not None:
''',
        '''    def reject(self):
        if self.quick_running:
            return
        if self.ai_models.task is not None:
''',
        'onboarding reject guard')
    onboarding = replace_once(onboarding,
        '''    def closeEvent(self, event):
        if self.ai_models.task is not None:
''',
        '''    def closeEvent(self, event):
        if self.quick_running:
            event.ignore()
            return
        if self.ai_models.task is not None:
''',
        'onboarding close guard')

    result = {'app.py': app, 'echobridge_model_ui.py': model_ui, 'echobridge_onboarding.py': onboarding}
    # Verify all changes in memory before modifying files, and never overwrite
    # the user's own autostart module unless it is identical.
    for name, src in result.items():
        ast.parse(src, filename=name)
    module_dest = project / 'echobridge_autostart.py'
    module_src = kit / 'echobridge_autostart.py'
    if module_dest.exists() and module_dest.read_bytes() != module_src.read_bytes():
        raise RuntimeError('Existing echobridge_autostart.py differs: refusing to overwrite')

    backup = project / '.echobridge_backups' / 'before_easy_installer'
    if backup.exists():
        raise RuntimeError('Backup folder already exists. Review it before rerunning.')
    backup.mkdir(parents=True)
    for name, path in files.items():
        shutil.copy2(path, backup / name)
    for name, src in result.items():
        files[name].write_text(src, encoding='utf-8')
    shutil.copy2(module_src, module_dest)
    print('Easy installer integration applied. Backups:', backup)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', default='.')
    opts = parser.parse_args()
    try:
        patch(Path(opts.project).resolve(), Path(__file__).resolve().parent)
    except (OSError, RuntimeError, SyntaxError) as exc:
        print('Update not applied:', exc, file=sys.stderr)
        sys.exit(1)
