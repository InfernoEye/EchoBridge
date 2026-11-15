"""Speech Models settings: hardware, downloads and safe removal.

Translation setup belongs on the separate Translations tab.
"""
from __future__ import annotations
from PySide6.QtCore import QSettings, QSignalBlocker, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from echobridge_models import (DEVICES, MODEL_FILES, MODELS, RUNTIMES, VAD_PATH,
                               vad_ready, model_ready, runtime_path, device_name, model_name)
from echobridge_gpus import detect_gpus, for_backend, resolve_choice
from echobridge_preload import find_server
from echobridge_tasks import SetupTask

SETTINGS = QSettings('EchoBridge', 'EchoBridge')
LANGUAGES = [
    ('English', 'en'), ('Polish', 'pl'), ('German', 'de'), ('Spanish', 'es'),
    ('French', 'fr'), ('Italian', 'it'), ('Portuguese', 'pt'),
    ('Ukrainian', 'uk'), ('Japanese', 'ja'), ('Chinese', 'zh'),
    ('Russian', 'ru'), ('Dutch', 'nl'), ('Czech', 'cs'), ('Turkish', 'tr')]


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class ModelSettingsPage(QWidget):
    taskCompleted = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.job = SetupTask(self)
        self.task = None  # compatibility with setup wizard and quit checks
        self.job.runningChanged.connect(self._running)
        self.job.progress.connect(self._progress)
        self.job.phase.connect(self._phase)
        self.job.finished.connect(self._finished)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(10)
        title = QLabel('Speech Models & Hardware')
        title.setObjectName('title')
        layout.addWidget(title)
        self.hint = self.message('Speech recognition runs locally. Models are stored on disk but unloaded from RAM after each task.')
        layout.addWidget(self.hint)
        layout.addWidget(self.heading('Processing device'))
        self.device = NoWheelComboBox()
        for name, label in DEVICES.items():
            self.device.addItem(label, name)
        self.select(self.device, device_name())
        layout.addWidget(self.device)
        self.device_info = self.message('')
        layout.addWidget(self.device_info)
        layout.addWidget(self.heading('Graphics card'))
        row = QHBoxLayout()
        self.gpu_select = NoWheelComboBox()
        self.gpu_select.currentIndexChanged.connect(self.gpu_changed)
        row.addWidget(self.gpu_select, 1)
        self.gpu_refresh = QPushButton('Refresh GPUs')
        self.gpu_refresh.clicked.connect(self.refresh_gpus)
        row.addWidget(self.gpu_refresh)
        layout.addLayout(row)
        self.gpu_status = self.message('')
        layout.addWidget(self.gpu_status)
        self.device.currentIndexChanged.connect(self.changed)

        layout.addWidget(self.heading('Speech transcription model'))
        self.model = NoWheelComboBox()
        readable = {
            'tiny': 'Tiny — fastest', 'base': 'Base — basic',
            'small': 'Small — recommended', 'medium': 'Medium — accurate',
            'large-v3-turbo-q5_0': 'Large v3 Turbo Q5 — fast and accurate',
            'large-v3': 'Large v3 — largest and slowest',
        }
        for code, (_, size) in MODEL_FILES.items():
            self.model.addItem(f'{readable[code]} ({size})', code)
        self.select(self.model, model_name())
        self.model.currentIndexChanged.connect(self.changed)
        layout.addWidget(self.model)
        layout.addWidget(self.heading('Installed status'))
        self.availability = self.message('')
        layout.addWidget(self.availability)

        row = QHBoxLayout()
        self.runtime_btn = QPushButton('Install runtime')
        self.runtime_btn.clicked.connect(self.install_runtime)
        self.model_btn = QPushButton('Download model')
        self.model_btn.setObjectName('primary')
        self.model_btn.clicked.connect(self.install_model)
        row.addWidget(self.runtime_btn)
        row.addWidget(self.model_btn)
        layout.addLayout(row)
        self.vad_btn = QPushButton('Install speech detector (~0.9 MB)')
        self.vad_btn.clicked.connect(self.install_vad)
        layout.addWidget(self.vad_btn)

        layout.addWidget(self.heading('Remove downloaded components'))
        self.installed_models = QListWidget()
        self.installed_models.setMaximumHeight(110)
        layout.addWidget(self.installed_models)
        self.remove_model_btn = QPushButton('Remove selected speech model')
        self.remove_model_btn.clicked.connect(self.remove_selected_model)
        layout.addWidget(self.remove_model_btn)
        row = QHBoxLayout()
        self.remove_runtime_btn = QPushButton('Remove selected runtime')
        self.remove_runtime_btn.clicked.connect(self.remove_runtime)
        self.remove_vad_btn = QPushButton('Remove speech detector')
        self.remove_vad_btn.clicked.connect(self.remove_vad)
        row.addWidget(self.remove_runtime_btn)
        row.addWidget(self.remove_vad_btn)
        layout.addLayout(row)
        self.status = self.message('')
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        layout.addStretch()
        self._controls = [self.runtime_btn, self.model_btn, self.vad_btn,
                          self.remove_model_btn, self.remove_runtime_btn,
                          self.remove_vad_btn, self.device, self.model,
                          self.gpu_select, self.gpu_refresh, self.installed_models]
        self.refresh_gpus()
        self.refresh()

    @staticmethod
    def heading(text):
        lab = QLabel(text)
        lab.setObjectName('section')
        return lab

    @staticmethod
    def message(text):
        lab = QLabel(text)
        lab.setObjectName('muted')
        lab.setWordWrap(True)
        return lab

    @staticmethod
    def select(combo, value):
        ix = combo.findData(str(value))
        if ix >= 0:
            combo.setCurrentIndex(ix)

    def changed(self):
        SETTINGS.setValue('whisper_device', self.device.currentData())
        SETTINGS.setValue('whisper_model', self.model.currentData())
        SETTINGS.sync()
        self.refresh_gpus()
        self.refresh()

    def gpu_changed(self, index):
        if index < 0:
            return
        data = self.gpu_select.itemData(index)
        if data:
            number, identity = data
            SETTINGS.setValue('vulkan_device', int(number))
            SETTINGS.setValue('vulkan_gpu_identity', identity)
            SETTINGS.sync()

    def refresh_gpus(self):
        device = str(self.device.currentData())
        visible = device != 'cpu'
        for widget in (self.gpu_select, self.gpu_refresh, self.gpu_status):
            widget.setVisible(visible)
        if not visible:
            self.device_info.setText('CPU — the easiest option for all Windows computers.')
            return
        self.device_info.setText('GPU acceleration needs current graphics drivers and a Vulkan-enabled runtime.')
        with QSignalBlocker(self.gpu_select):
            self.gpu_select.clear()
            try:
                devices = for_backend(detect_gpus(), device)
                for gpu in devices:
                    self.gpu_select.addItem(gpu.label, (gpu.index, gpu.identity))
                if not devices:
                    self.gpu_select.addItem('No compatible graphics card detected', None)
                    self.gpu_status.setText('Choose CPU or update your GPU driver.')
                    self.gpu_select.setEnabled(False)
                    return
                stored_id = str(SETTINGS.value('vulkan_gpu_identity', '') or '')
                chosen = resolve_choice(devices, device, stored_id, int(SETTINGS.value('vulkan_device', 0)))
                ix = next(i for i, gpu in enumerate(devices) if gpu.index == chosen.index)
                self.gpu_select.setCurrentIndex(ix)
                self.gpu_status.setText(f'{len(devices)} compatible GPU(s) available.')
                self.gpu_select.setEnabled(True)
            except (RuntimeError, OSError, ValueError) as exc:
                self.gpu_status.setText(f'Graphics card unavailable: {exc}')
                self.gpu_select.setEnabled(False)

    def refresh(self):
        selected = str(self.model.currentData())
        device = str(self.device.currentData())
        cli = runtime_path(device)
        self.availability.setText(
            f'Model {selected}: {"Installed" if model_ready(selected) else "Not installed"}\n'
            f'{device.upper()} runtime: {"Installed (preload enabled)" if find_server(cli) else "Missing / outdated"}\n'
            f'Speech detector: {"Installed" if vad_ready() else "Not installed"}'
        )
        self.runtime_btn.setText('Reinstall runtime' if cli else 'Install runtime')
        self.model_btn.setText('Model installed' if model_ready(selected) else 'Download selected model')
        self.model_btn.setEnabled(not model_ready(selected) and not self.job.running)
        with QSignalBlocker(self.installed_models):
            current = self.installed_models.currentItem()
            previous = current.data(256) if current else None
            self.installed_models.clear()
            for name in MODEL_FILES:
                if model_ready(name):
                    from PySide6.QtWidgets import QListWidgetItem
                    item = QListWidgetItem(f'{name}  —  {MODEL_FILES[name][1]}')
                    item.setData(256, name)
                    self.installed_models.addItem(item)
                    if previous == name:
                        self.installed_models.setCurrentItem(item)
        self.remove_runtime_btn.setEnabled(bool(cli) and not self.job.running)
        self.remove_vad_btn.setEnabled(vad_ready() and not self.job.running)
        self.remove_model_btn.setEnabled(self.installed_models.count() > 0 and not self.job.running)

    def sync_from_general(self):
        self.refresh()

    def _ready_for_changes(self):
        owner = self.window()
        controller = getattr(owner, 'controller', None)
        runtime = getattr(controller, 'runtime', None)
        if runtime is not None and runtime.state != 'idle':
            QMessageBox.warning(self, 'EchoBridge', 'Finish the current recording or translation first.')
            return False
        return True

    def install_model(self):
        name = str(self.model.currentData())
        if model_ready(name) or not self._ready_for_changes():
            return
        self.launch(['--model', name], f'Whisper model {name}')

    def install_runtime(self):
        if not self._ready_for_changes():
            return
        backend = str(self.device.currentData())
        if backend != 'cpu':
            answer = QMessageBox.question(self, 'Vulkan runtime',
                'Install the third-party Vulkan build of whisper.cpp from GitHub? '
                'This is required for AMD and NVIDIA GPU acceleration.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.launch(['--runtime', 'cpu' if backend == 'cpu' else 'gpu'], 'Speech runtime')

    def install_vad(self):
        if not vad_ready() and self._ready_for_changes():
            self.launch(['--vad'], 'Speech detector')

    def remove_selected_model(self):
        item = self.installed_models.currentItem()
        if not item or not self._ready_for_changes():
            return
        name = item.data(256)
        if self._confirm(f'Delete downloaded Whisper {name}? This cannot be undone.'):
            self.launch(['--remove-model', name], f'Remove {name}')

    def remove_runtime(self):
        if not self._ready_for_changes():
            return
        device = str(self.device.currentData())
        backend = 'cpu' if device == 'cpu' else 'gpu'
        if self._confirm(f'Remove the installed {backend.upper()} transcription runtime?'):
            self.launch(['--remove-runtime', backend], f'Remove {backend.upper()} runtime')

    def remove_vad(self):
        if self._ready_for_changes() and self._confirm('Remove the installed speech detector?'):
            self.launch(['--remove-vad'], 'Remove speech detector')

    def _confirm(self, message):
        return QMessageBox.question(self, 'EchoBridge — Remove component', message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def launch(self, args, description='AI setup'):
        if self.job.running or not self._ready_for_changes():
            return False
        self.job.start(args, description)
        return True

    def _running(self, active):
        self.task = self.job.process if active else None
        for widget in self._controls:
            widget.setEnabled(not active)
        if active:
            self.progress.show()
        else:
            self.refresh()

    def _progress(self, value):
        if value == -1:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(value)

    def _phase(self, message):
        self.status.setText(message)

    def _finished(self, success, message):
        self.progress.hide()
        self.refresh()
        self.taskCompleted.emit(success)
        if not getattr(self, 'batch_mode', False):
            if success:
                QMessageBox.information(self, 'EchoBridge', message)
            else:
                QMessageBox.warning(self, 'EchoBridge — Setup failed', message)

    def stop_setup(self):
        self.job.stop()
