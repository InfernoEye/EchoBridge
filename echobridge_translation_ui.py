"""Dedicated Translations settings; speech-language selection is not a package selector."""
from __future__ import annotations
from PySide6.QtCore import QSettings, QSignalBlocker, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QVBoxLayout, QWidget)

from echobridge_model_ui import LANGUAGES, NoWheelComboBox
from echobridge_languages import SPEECH_LANGUAGES, normalize_speech_language
from echobridge_translation_routes import plan_translation
from echobridge_tasks import SetupTask

SETTINGS = QSettings('EchoBridge', 'EchoBridge')


def installed_pairs():
    try:
        import argostranslate.package as pkg
        return sorted({(p.from_code, p.to_code) for p in pkg.get_installed_packages()
                       if getattr(p, 'type', 'translate') == 'translate'})
    except (ImportError, OSError):
        return []


def route_ready(source, target):
    if source == target:
        return True
    try:
        plan_translation(source, target, set(installed_pairs()))
        return True
    except (ValueError, RuntimeError):
        return False


class TranslationSettingsPage(QWidget):
    taskCompleted = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.job = SetupTask(self)
        self.job.phase.connect(self._phase)
        self.job.progress.connect(self._progress)
        self.job.runningChanged.connect(self._running)
        self.job.finished.connect(self._finished)
        layout_outer = QVBoxLayout(self)
        layout_outer.setContentsMargins(0, 0, 0, 0)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        layout_outer.addWidget(scroller)
        body = QWidget()
        scroller.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(10)
        heading = QLabel('Translations')
        heading.setObjectName('title')
        layout.addWidget(heading)
        layout.addWidget(self.note('Choose the language you speak and the language you want EchoBridge to translate into.'))
        layout.addWidget(self.heading('Speech language (input)'))
        self.speech_language = NoWheelComboBox()
        for code, name in SPEECH_LANGUAGES:
            self.speech_language.addItem(name, code)
        self._select(self.speech_language, normalize_speech_language(SETTINGS.value('speech_language', 'auto')))
        self.speech_language.currentIndexChanged.connect(self.changed)
        layout.addWidget(self.speech_language)
        layout.addWidget(self.note('Automatic detects speech language. For short phrases, choosing Polish, English, etc. is more reliable.'))

        layout.addWidget(self.heading('Translate into (target)'))
        self.target = NoWheelComboBox()
        for name, code in LANGUAGES:
            self.target.addItem(name, code)
        self._select(self.target, SETTINGS.value('language', 'en'))
        self.target.currentIndexChanged.connect(self.changed)
        layout.addWidget(self.target)

        layout.addWidget(self.heading('Download offline translation package'))
        layout.addWidget(self.note('Pick the language of the translation package. With Automatic speech detection, install packages for each language you commonly speak.'))
        self.package_source = NoWheelComboBox()
        for name, code in LANGUAGES:
            self.package_source.addItem(name, code)
        self._select(self.package_source, SETTINGS.value('translation_source', 'pl'))
        self.package_source.currentIndexChanged.connect(self.changed_package_source)
        layout.addWidget(self.package_source)
        self.pair_status = self.note('')
        layout.addWidget(self.pair_status)
        self.install_btn = QPushButton('Download selected translation package')
        self.install_btn.setObjectName('primary')
        self.install_btn.clicked.connect(self.install)
        layout.addWidget(self.install_btn)

        layout.addWidget(self.heading('Installed language packages'))
        self.installed_list = QListWidget()
        self.installed_list.setMinimumHeight(110)
        self.installed_list.setMaximumHeight(150)
        layout.addWidget(self.installed_list)
        row = QHBoxLayout()
        self.refresh_btn = QPushButton('Refresh packages')
        self.refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self.refresh_btn)
        self.remove_btn = QPushButton('Remove selected package')
        self.remove_btn.clicked.connect(self.remove)
        row.addWidget(self.remove_btn)
        layout.addLayout(row)
        self.status = self.note('')
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        layout.addStretch()
        self._controls = (self.speech_language, self.target,
                          self.package_source, self.install_btn,
                          self.installed_list, self.refresh_btn, self.remove_btn)
        self.refresh()

    @staticmethod
    def heading(text):
        l = QLabel(text)
        l.setObjectName('section')
        return l

    @staticmethod
    def note(text):
        l = QLabel(text)
        l.setObjectName('muted')
        l.setWordWrap(True)
        return l

    @staticmethod
    def _select(combo, value):
        index = combo.findData(str(value))
        if index >= 0:
            combo.setCurrentIndex(index)

    def changed(self):
        source = normalize_speech_language(self.speech_language.currentData())
        target = str(self.target.currentData())
        SETTINGS.setValue('speech_language', source)
        SETTINGS.setValue('language', target)
        if source != 'auto':
            SETTINGS.setValue('translation_source', source)
            self._select(self.package_source, source)
        SETTINGS.sync()
        self.refresh()

    def changed_package_source(self):
        SETTINGS.setValue('translation_source', self.package_source.currentData())
        SETTINGS.sync()
        self.refresh()

    def refresh(self):
        source = str(self.package_source.currentData())
        target = str(self.target.currentData())
        ready = route_ready(source, target)
        self.pair_status.setText(
            f'Package: {self.package_source.currentText()} → {self.target.currentText()}\n'
            + ('Ready for offline translation' if ready else 'Not installed — download below')
        )
        with QSignalBlocker(self.installed_list):
            selected = self.installed_list.currentItem()
            previous = selected.data(256) if selected else None
            self.installed_list.clear()
            names = {code: name for name, code in LANGUAGES}
            for a, b in installed_pairs():
                label = f'{names.get(a, a)} → {names.get(b, b)}'
                item = QListWidgetItem(label)
                item.setData(256, (a, b))
                self.installed_list.addItem(item)
                if previous == (a, b):
                    self.installed_list.setCurrentItem(item)
        self.remove_btn.setEnabled(bool(self.installed_list.count()) and not self.job.running)
        self.install_btn.setEnabled(not ready and not self.job.running)
        self.install_btn.setText('Already installed' if ready else 'Download selected translation package')

    def _ready_for_changes(self):
        controller = getattr(self.window(), 'controller', None)
        runtime = getattr(controller, 'runtime', None)
        if runtime is not None and runtime.state != 'idle':
            QMessageBox.warning(self, 'EchoBridge', 'Finish your recording or translation before changing packages.')
            return False
        return True

    def install(self):
        if self.job.running or not self._ready_for_changes():
            return
        source, target = str(self.package_source.currentData()), str(self.target.currentData())
        if source == target:
            return
        self.job.start(['--pair', source, target], f'Offline translation {source} → {target}')

    def remove(self):
        item = self.installed_list.currentItem()
        if self.job.running or item is None or not self._ready_for_changes():
            return
        source, target = item.data(256)
        result = QMessageBox.question(self, 'Remove translation',
            f'Remove installed offline translation package {source} → {target}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if result == QMessageBox.StandardButton.Yes:
            self.job.start(['--remove-pair', source, target], f'Removing {source} → {target}')

    def _running(self, yes):
        for widget in self._controls:
            widget.setEnabled(not yes)
        if yes:
            self.progress.show()
        else:
            self.refresh()

    def _phase(self, message):
        self.status.setText(message)

    def _progress(self, value):
        if value < 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(value)

    def _finished(self, success, message):
        self.progress.hide()
        self.refresh()
        self.taskCompleted.emit(success)
        (QMessageBox.information if success else QMessageBox.warning)(
            self, 'EchoBridge — Translation packages', message)
