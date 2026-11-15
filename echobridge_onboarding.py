"""Guided first-run wizard: pick microphone/languages, install four components, use app."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QCheckBox, QProgressBar, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)
import sounddevice as sd

from echobridge_capture import MicrophoneTest
from echobridge_hotkey import parse_hotkey
from echobridge_languages import SPEECH_LANGUAGES, normalize_speech_language
from echobridge_microphones import active_microphones, normalize_selection, resolve_input
from echobridge_model_ui import LANGUAGES, NoWheelComboBox
from echobridge_models import DEVICES, MODEL_FILES, device_name, model_name, model_ready, vad_ready, runtime_path
from echobridge_preload import find_server
from echobridge_translation_ui import route_ready
from echobridge_tasks import SetupTask
from echobridge_gpus import detect_gpus, for_backend

SETTINGS = QSettings('EchoBridge', 'EchoBridge')


def readiness():
    speech = normalize_speech_language(SETTINGS.value('speech_language', 'auto'))
    source = speech if speech != 'auto' else str(SETTINGS.value('translation_source', 'pl'))
    target = str(SETTINGS.value('language', 'en'))
    device = device_name()
    return (model_ready(model_name()),
            find_server(runtime_path(device)) is not None,
            vad_ready(), route_ready(source, target), source, target)


class FirstRunWizard(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.index = 0
        self.test = None
        self.capturing = False
        self.job = SetupTask(self)
        self.job.phase.connect(self._phase)
        self.job.progress.connect(self._progress)
        self.job.runningChanged.connect(self._running)
        self.job.finished.connect(self._finished)
        self.setWindowTitle('EchoBridge — Welcome')
        self.setMinimumSize(620, 700)
        self.resize(650, 725)
        main = QVBoxLayout(self)
        main.setContentsMargins(22, 18, 22, 18)
        self.heading = QLabel('Welcome to EchoBridge')
        self.heading.setObjectName('title')
        main.addWidget(self.heading)
        self.description = self.note('Step 1 of 3 — Configure')
        main.addWidget(self.description)
        self.pages = QStackedWidget()
        main.addWidget(self.pages, 1)
        self.pages.addWidget(self.create_basics_page())
        self.pages.addWidget(self.create_install_page())
        self.pages.addWidget(self.create_review_page())
        footer = QHBoxLayout()
        self.later = QPushButton('Set up later')
        self.later.clicked.connect(self.reject)
        footer.addWidget(self.later)
        footer.addStretch()
        self.previous = QPushButton('Back')
        self.previous.clicked.connect(self.go_back)
        footer.addWidget(self.previous)
        self.next = QPushButton('Install & Continue')
        self.next.setObjectName('primary')
        self.next.clicked.connect(self.go_next)
        footer.addWidget(self.next)
        main.addLayout(footer)
        self.meter_timer = QTimer(self)
        self.meter_timer.setInterval(100)
        self.meter_timer.timeout.connect(self.update_mic_test)
        self.refresh_microphones()
        self.update_step()

    @staticmethod
    def note(text):
        l = QLabel(text)
        l.setWordWrap(True)
        l.setObjectName('muted')
        return l

    @staticmethod
    def label(text):
        l = QLabel(text)
        l.setObjectName('section')
        return l

    def create_basics_page(self):
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(9)
        layout.setContentsMargins(10, 10, 14, 10)
        layout.addWidget(self.label('1. Microphone'))
        row = QHBoxLayout()
        self.microphone = NoWheelComboBox()
        row.addWidget(self.microphone, 1)
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self.refresh_microphones)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.mic_status = self.note('Only enabled Windows microphones are shown.')
        layout.addWidget(self.mic_status)
        self.mic_meter = QProgressBar()
        self.mic_meter.setRange(0, 100)
        self.mic_meter.setValue(0)
        self.mic_meter.setFixedHeight(12)
        self.mic_meter.setTextVisible(False)
        layout.addWidget(self.mic_meter)
        self.mic_test_btn = QPushButton('Test microphone')
        self.mic_test_btn.clicked.connect(self.toggle_mic_test)
        layout.addWidget(self.mic_test_btn)
        self.instant_capture = QCheckBox('Instant capture: no microphone startup delay on F8')
        self.instant_capture.setChecked(SETTINGS.value('instant_capture', True, type=bool))
        layout.addWidget(self.instant_capture)
        layout.addWidget(self.note(
            'Optional: keeps the mic actively in use by Windows while EchoBridge runs, '
            'but discards all audio while idle. Disable to use the mic only when F8 is held.'
        ))
        layout.addWidget(self.label('2. Which language do you speak?'))
        self.source = NoWheelComboBox()
        for code, name in SPEECH_LANGUAGES:
            self.source.addItem(name, code)
        self.select(self.source, normalize_speech_language(SETTINGS.value('speech_language', 'auto')))
        self.source.currentIndexChanged.connect(self.source_changed)
        layout.addWidget(self.source)
        layout.addWidget(self.note('Automatic detects spoken language. Choose a specific language for more reliable short-phrase recognition.'))
        layout.addWidget(self.label('3. Main language for offline translation packages'))
        self.package_source = NoWheelComboBox()
        for name, code in LANGUAGES:
            self.package_source.addItem(name, code)
        self.select(self.package_source, SETTINGS.value('translation_source', 'pl'))
        layout.addWidget(self.package_source)
        layout.addWidget(self.note('If speech detection is Automatic, this is the language we prepare for translation now. You can add other languages later.'))
        layout.addWidget(self.label('4. Translate into'))
        self.target = NoWheelComboBox()
        for name, code in LANGUAGES:
            self.target.addItem(name, code)
        self.select(self.target, SETTINGS.value('language', 'en'))
        layout.addWidget(self.target)
        layout.addWidget(self.label('5. Speech processing hardware'))
        self.device = NoWheelComboBox()
        for code, label in DEVICES.items():
            self.device.addItem(('Recommended: ' if code == 'cpu' else '') + label, code)
        self.select(self.device, device_name())
        self.device.currentIndexChanged.connect(self.update_gpu_options)
        layout.addWidget(self.device)
        self.gpu = NoWheelComboBox()
        layout.addWidget(self.gpu)
        self.gpu_message = self.note('CPU is compatible with all Windows machines. GPU requires a Vulkan-compatible graphics driver.')
        layout.addWidget(self.gpu_message)
        self.update_gpu_options()
        layout.addWidget(self.label('6. Whisper model'))
        self.model = NoWheelComboBox()
        for code, (_, size) in MODEL_FILES.items():
            label = f'{code} · {size}' + (' (Recommended)' if code == 'small' else '')
            self.model.addItem(label, code)
        self.select(self.model, model_name())
        layout.addWidget(self.model)
        layout.addWidget(self.note('Small is recommended for most computers; larger models take longer to download and load.'))
        layout.addWidget(self.label('7. Recording shortcut'))
        self.hotkey = QPushButton(str(SETTINGS.value('hotkey', 'F8')))
        self.hotkey.clicked.connect(self.start_hotkey_capture)
        self.hotkey.installEventFilter(self)
        layout.addWidget(self.hotkey)
        layout.addWidget(self.note('Hold this key to record; release it to transcribe. F8 is the default.'))
        layout.addStretch()
        scroller.setWidget(body)
        return scroller

    @staticmethod
    def select(combo, value):
        ix = combo.findData(str(value))
        if ix >= 0:
            combo.setCurrentIndex(ix)

    def create_install_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(14)
        layout.addWidget(self.label('Installing everything you need'))
        layout.addWidget(self.note('EchoBridge downloads a Windows speech runtime, a Whisper model, the speech detector (~0.9 MB), and the offline translation package. Downloads happen once during setup, not during recording.'))
        self.install_summary = self.note('')
        layout.addWidget(self.install_summary)
        self.install_phase = self.note('Ready to install')
        layout.addWidget(self.install_phase)
        self.install_progress = QProgressBar()
        self.install_progress.hide()
        layout.addWidget(self.install_progress)
        self.retry = QPushButton('Retry installation')
        self.retry.clicked.connect(self.start_install)
        self.retry.hide()
        layout.addWidget(self.retry)
        layout.addWidget(self.note('If a download fails, EchoBridge keeps already installed components. Retry resumes by skipping verified files.'))
        layout.addStretch()
        return page

    def create_review_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(14)
        layout.addWidget(self.label('EchoBridge is almost ready'))
        self.review = self.note('Checking installed components...')
        layout.addWidget(self.review)
        self.ready = self.note('')
        layout.addWidget(self.ready)
        check = QPushButton('Check again')
        check.clicked.connect(self.refresh_review)
        layout.addWidget(check)
        layout.addStretch()
        return page

    def update_gpu_options(self):
        backend = str(self.device.currentData())
        self.gpu.setVisible(backend != 'cpu')
        if backend == 'cpu':
            self.gpu_message.setText('Recommended: CPU works on any Windows PC. You can change this later.')
            return
        self.gpu.clear()
        try:
            options = for_backend(detect_gpus(), backend)
            for gpu in options:
                self.gpu.addItem(gpu.name, (gpu.index, gpu.identity))
            if options:
                self.gpu_message.setText(f'Found {len(options)} compatible {backend.upper()} graphics card(s).')
            else:
                self.gpu.addItem('No compatible graphics card', None)
                self.gpu_message.setText('No compatible GPU found. Choose CPU instead.')
        except (OSError, RuntimeError, ValueError) as exc:
            self.gpu.addItem('GPU detection failed', None)
            self.gpu_message.setText(str(exc))

    def source_changed(self):
        code = str(self.source.currentData())
        if code != 'auto':
            with QSignalBlocker(self.package_source):
                self.select(self.package_source, code)

    def refresh_microphones(self):
        self.stop_mic_test()
        selected = str(SETTINGS.value('microphone', 'default'))
        if self.microphone.currentData() is not None:
            selected = str(self.microphone.currentData())
        with QSignalBlocker(self.microphone):
            self.microphone.clear()
            try:
                found = active_microphones(sd)
                if not found:
                    self.microphone.addItem('No enabled microphones found', None)
                    self.mic_status.setText('Enable a microphone in Windows Sound settings, then Refresh.')
                    return
                self.microphone.addItem('Windows Default Microphone', 'default')
                for mic in found:
                    self.microphone.addItem(mic.label, mic.token)
                self.select(self.microphone, normalize_selection(sd, selected))
                self.mic_status.setText(f'{len(found)} available microphone(s).')
            except Exception as exc:
                self.microphone.addItem('Microphones unavailable', None)
                self.mic_status.setText(str(exc))

    def toggle_mic_test(self):
        if self.test:
            self.stop_mic_test()
            return
        token = self.microphone.currentData()
        if token is None:
            self.mic_status.setText('Choose a microphone first.')
            return
        # Stopped, pre-armed audio stream must be released for exclusive mic tests.
        self.controller.runtime.recorder.release()
        try:
            test = MicrophoneTest(sd, str(token), resolve_input)
            test.start()
            self.test = test
            self.mic_test_btn.setText('Stop microphone test')
            self.mic_status.setText('Speak into your microphone...')
            self.meter_timer.start()
        except Exception as exc:
            self.mic_status.setText(f'Microphone test failed: {exc}')

    def update_mic_test(self):
        if self.test:
            self.mic_meter.setValue(self.test.level_percent())
            if self.test.samples:
                self.mic_status.setText(f'Audio input: {self.test.device_name} · peak {self.test.peak_db:.0f} dBFS')

    def stop_mic_test(self):
        if not hasattr(self, 'meter_timer'):
            return
        self.meter_timer.stop()
        if self.test:
            try:
                self.test.stop()
            finally:
                self.test = None
                QTimer.singleShot(0, self.controller.runtime.arm_microphone)
        self.mic_test_btn.setText('Test microphone')
        self.mic_meter.setValue(0)

    def start_hotkey_capture(self):
        self.capturing = True
        self.hotkey.setText('Press a key (Esc cancels)')
        self.hotkey.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.hotkey and self.capturing and event.type() == QEvent.Type.KeyPress:
            if event.isAutoRepeat():
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.hotkey.setText(str(SETTINGS.value('hotkey', 'F8')))
            else:
                code = QKeySequence(event.keyCombination()).toString()
                try:
                    parse_hotkey(code)
                    self.controller.runtime.set_hotkey(code)
                    self.hotkey.setText(code)
                    self.controller.window.key_button.setText(code)
                except ValueError:
                    self.hotkey.setText(str(SETTINGS.value('hotkey', 'F8')))
            self.capturing = False
            return True
        return super().eventFilter(obj, event)

    def store_basics(self):
        self.stop_mic_test()
        if self.microphone.currentData() is None:
            QMessageBox.warning(self, 'EchoBridge', 'Choose an enabled microphone.')
            return False
        source = normalize_speech_language(self.source.currentData())
        package_source = str(self.package_source.currentData())
        target = str(self.target.currentData())
        backend = str(self.device.currentData())
        if backend != 'cpu':
            gpu = self.gpu.currentData()
            if gpu is None:
                QMessageBox.warning(self, 'EchoBridge', 'No compatible GPU detected. Choose CPU to continue.')
                return False
            SETTINGS.setValue('vulkan_device', int(gpu[0]))
            SETTINGS.setValue('vulkan_gpu_identity', gpu[1])
        SETTINGS.setValue('whisper_device', backend)
        SETTINGS.setValue('whisper_model', self.model.currentData())
        SETTINGS.setValue('microphone', self.microphone.currentData())
        SETTINGS.setValue('speech_language', source)
        SETTINGS.setValue('translation_source', package_source)
        SETTINGS.setValue('language', target)
        SETTINGS.setValue('instant_capture', self.instant_capture.isChecked())
        SETTINGS.sync()
        general = self.controller.window
        general.refresh_microphones()
        with QSignalBlocker(general.translation.speech_language):
            self.select(general.translation.speech_language, source)
        with QSignalBlocker(general.translation.package_source):
            self.select(general.translation.package_source, package_source)
        with QSignalBlocker(general.translation.target):
            self.select(general.translation.target, target)
        general.translation.refresh()
        with QSignalBlocker(general.instant_capture_toggle):
            general.instant_capture_toggle.setChecked(self.instant_capture.isChecked())
        # Refresh the audio mode and chosen device after the wizard changes.
        self.controller.runtime.recorder.release()
        self.controller.runtime.set_instant_capture(self.instant_capture.isChecked())
        return True

    def start_install(self):
        if self.job.running:
            return
        device = device_name()
        if device != 'cpu' and find_server(runtime_path(device)) is None:
            answer = QMessageBox.question(self, 'EchoBridge — GPU runtime',
                'GPU acceleration requires a third-party Vulkan binary from GitHub. Install it now?\n\n'
                'Choose CPU in Settings → AI Models if you prefer the official CPU runtime.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.install_phase.setText('GPU runtime download cancelled. Choose CPU or retry.')
                self.retry.show()
                return
        source = str(SETTINGS.value('translation_source', 'pl'))
        target = str(SETTINGS.value('language', 'en'))
        self.retry.hide()
        self.install_summary.setText(f'Using {device.upper()} · Whisper {model_name()}\n'
            f'Translation package: {source} → {target}')
        self.job.start(['--bundle', device, model_name(), source, target], 'EchoBridge components')

    def _running(self, running):
        self.install_progress.setVisible(running)
        self.next.setEnabled(not running)
        self.previous.setEnabled(not running)
        self.later.setEnabled(not running)
        self.retry.setEnabled(not running)

    def _phase(self, message):
        self.install_phase.setText(message)

    def _progress(self, number):
        if number < 0:
            self.install_progress.setRange(0, 0)
        else:
            self.install_progress.setRange(0, 100)
            self.install_progress.setValue(number)

    def _finished(self, success, message):
        if success:
            self.install_phase.setText('All components installed and verified.')
            self.index = 2
            self.update_step()
        else:
            self.install_phase.setText(f'Installation error: {message}')
            self.retry.show()
            QMessageBox.warning(self, 'EchoBridge — Download failed',
                f'{message}\n\nYou can retry without losing successful downloads.')

    def refresh_review(self):
        model, runtime, vad, translation, source, target = readiness()
        mark = lambda ready: '✓ Installed' if ready else '✕ Missing'
        self.review.setText(
            f'Speech language: {self.source.currentText()}\n'
            f'Translate: {source} → {target}\n'
            f'Hotkey: {SETTINGS.value("hotkey", "F8")}\n\n'
            f'Whisper model: {mark(model)}\n'
            f'Processing runtime + preload: {mark(runtime)}\n'
            f'Speech detector: {mark(vad)}\n'
            f'Offline translation: {mark(translation)}')
        all_ready = model and runtime and vad and translation
        self.ready.setText('Ready! You can now hold your recording key.' if all_ready else
                           'Some files are missing. Click Back and retry installation.')
        return all_ready

    def update_step(self):
        self.pages.setCurrentIndex(self.index)
        labels = ['Choose your preferences', 'Download required components', 'Ready to go']
        self.description.setText(f'Step {self.index + 1} of 3 — {labels[self.index]}')
        self.previous.setEnabled(self.index > 0 and not self.job.running)
        self.next.setEnabled(not self.job.running)
        self.next.setText('Install & Continue' if self.index == 0 else
                          'Finish setup' if self.index == 2 else 'Next')
        if self.index == 2:
            self.refresh_review()

    def go_back(self):
        if self.job.running:
            return
        if self.index > 0:
            self.index -= 1
            self.update_step()

    def go_next(self):
        if self.job.running:
            return
        if self.index == 0:
            if not self.store_basics():
                return
            self.index = 1
            self.update_step()
            QTimer.singleShot(0, self.start_install)
        elif self.index == 1:
            if self.refresh_review():
                self.index = 2
                self.update_step()
            else:
                self.start_install()
        else:
            if not self.refresh_review():
                QMessageBox.warning(self, 'EchoBridge', 'Complete the installation before finishing setup.')
                return
            SETTINGS.setValue('onboarding_completed_v2', True)
            SETTINGS.setValue('onboarding_completed_v3', True)
            SETTINGS.setValue('first_run', False)
            SETTINGS.sync()
            self.accept()

    def reject(self):
        if self.job.running:
            QMessageBox.information(self, 'EchoBridge', 'Wait until the active download finishes.')
            return
        self.stop_mic_test()
        super().reject()

    def closeEvent(self, event):
        if self.job.running:
            event.ignore()
            return
        self.stop_mic_test()
        super().closeEvent(event)
