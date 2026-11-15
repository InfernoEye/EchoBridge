import json
import sys
from datetime import datetime
from pathlib import Path

import sounddevice as sd
from echobridge_runtime import EchoBridgeRuntime
from echobridge_languages import SPEECH_LANGUAGES, normalize_speech_language
from echobridge_microphones import active_microphones, normalize_selection, resolve_input
from echobridge_capture import MicrophoneTest
from echobridge_model_ui import ModelSettingsPage, NoWheelComboBox, LANGUAGES
from echobridge_translation_ui import TranslationSettingsPage
from echobridge_onboarding import FirstRunWizard
from echobridge_autostart import installed_executable, enabled as autostart_enabled, set_enabled as set_autostart
from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, QStandardPaths
from PySide6.QtGui import (
    QAction, QColor, QFont, QGuiApplication,
    QIcon, QKeySequence, QPainter, QPixmap
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QCheckBox, QDialog, QFrame, QHBoxLayout,
    QFileDialog, QLabel, QListWidget, QMainWindow, QMenu, QPushButton,
    QScrollArea, QSpinBox, QProgressBar, QSystemTrayIcon, QTextEdit,
    QVBoxLayout, QWidget
)

settings = QSettings("EchoBridge", "EchoBridge")

STYLE = """
QWidget {
    background: #101116;
    color: #F0F0F5;
    font-family: 'Segoe UI';
    font-size: 12px;
}
QLabel#title {
    font-size: 23px;
    font-weight: 700;
}
QLabel#muted {
    color: #9698A7;
}
QLabel#section {
    color: #BBBCCB;
    font-weight: 600;
}
QComboBox, QSpinBox, QPushButton, QTextEdit, QListWidget {
    background: #1C1E28;
    border: 1px solid #323543;
    border-radius: 8px;
    padding: 8px;
}
QComboBox:hover, QSpinBox:hover, QPushButton:hover {
    border-color: #8074ED;
}
QComboBox::drop-down {
    border: 0;
    width: 24px;
}
QPushButton#primary {
    background: #7064E8;
    border: 0;
    font-weight: 600;
}
QPushButton#primary:hover {
    background: #8378F3;
}
QPushButton#small {
    padding: 5px 8px;
    font-size: 11px;
}
QFrame#card {
    background: #191B25;
    border: 1px solid #303240;
    border-radius: 11px;
}
QFrame#card QLabel {
    background: transparent;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
"""


def app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#7064E8"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(3, 3, 58, 58, 17, 17)

    painter.setPen(QColor("white"))
    font = QFont("Segoe UI", 30)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(
        pixmap.rect(),
        Qt.AlignmentFlag.AlignCenter,
        "E"
    )
    painter.end()

    return QIcon(pixmap)


def corner_position(widget, y_offset=16):
    screen = QGuiApplication.primaryScreen()

    if screen:
        rect = screen.availableGeometry()
        widget.move(
            rect.right() - widget.width() - 16,
            rect.top() + y_offset
        )


class StatusIndicator(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowDoesNotAcceptFocus |
            Qt.WindowType.WindowTransparentForInput
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )

        self.setFixedSize(165, 34)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel("Listening...")
        self.label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.label.setStyleSheet("""
            QLabel {
                background: #20212E;
                color: #A8A0FF;
                border: 1px solid #47415F;
                border-radius: 14px;
                font-size: 11px;
                font-weight: 600;
                padding: 6px;
            }
        """)

        outer.addWidget(self.label)
        corner_position(self)
        self.hide()

    def set_status(self, message):
        self.label.setText(message)

        if message.strip():
            corner_position(self)
            self.show()
        else:
            self.hide()


class TranslationPopup(QWidget):
    def __init__(
        self,
        original,
        translated,
        source,
        target,
        timeout,
        leave_timeout
    ):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )

        self.setFixedSize(328, 286)

        self.timeout = max(1, int(timeout))
        self.leave_timeout = max(1, int(leave_timeout))

        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.timeout.connect(self.close)

        outside = QVBoxLayout(self)
        outside.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("card")
        outside.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 11, 12, 11)
        layout.setSpacing(7)

        header = QHBoxLayout()

        title = QLabel("✦ EchoBridge")
        title.setStyleSheet(
            "font-weight: 700; font-size: 13px;"
        )
        header.addWidget(title)
        header.addStretch()

        close = QPushButton("×")
        close.setObjectName("small")
        close.setFixedSize(27, 26)
        close.clicked.connect(self.close)

        header.addWidget(close)
        layout.addLayout(header)

        languages = QLabel(f"{source}  →  {target}")
        languages.setObjectName("muted")
        layout.addWidget(languages)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(1, 2, 3, 2)
        column.setSpacing(7)

        for heading, value in [
            ("ORIGINAL", original),
            ("TRANSLATION", translated)
        ]:
            label = QLabel(heading)
            label.setStyleSheet(
                "color: #A4A5B8;"
                "font-size: 10px;"
                "font-weight: 700;"
            )
            column.addWidget(label)

            text = QLabel(value)
            text.setWordWrap(True)
            text.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            text.setStyleSheet("font-size: 12px;")
            column.addWidget(text)

        column.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

        actions = QHBoxLayout()

        for label, value in [
            ("Copy Original", original),
            ("Copy Translation", translated)
        ]:
            button = QPushButton(label)
            button.setObjectName("small")
            button.clicked.connect(
                lambda checked=False, text=value:
                QApplication.clipboard().setText(text)
            )
            actions.addWidget(button)

        layout.addLayout(actions)

        corner_position(self, 16)
        self.show()

        QTimer.singleShot(
            0,
            self._enforce_no_activation
        )

        self.dismiss_timer.start(
            self.timeout * 1000
        )

    def _enforce_no_activation(self):
        if sys.platform == "win32":
            import ctypes

            HWND_TOPMOST = -1
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010

            ctypes.windll.user32.SetWindowPos(
                int(self.winId()),
                HWND_TOPMOST,
                0, 0, 0, 0,
                SWP_NOSIZE |
                SWP_NOMOVE |
                SWP_NOACTIVATE
            )

    def enterEvent(self, event):
        self.dismiss_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.dismiss_timer.start(
            self.leave_timeout * 1000
        )
        super().leaveEvent(event)


class RecentTranslations(QDialog):
    def __init__(self, entries, parent=None):
        super().__init__(parent)

        self.entries = entries

        self.setWindowTitle(
            "EchoBridge — Recent Translations"
        )
        self.resize(470, 440)

        layout = QVBoxLayout(self)

        title = QLabel("Recent Translations")
        title.setObjectName("title")
        layout.addWidget(title)

        self.items = QListWidget()

        for entry in reversed(entries):
            short = entry.get(
                "original", ""
            )[:60].replace("\n", " ")

            self.items.addItem(
                f"{entry.get('time', '')}  ·  {short}"
            )

        layout.addWidget(self.items)

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details)

        self.items.currentRowChanged.connect(
            self.display_item
        )

        if entries:
            self.items.setCurrentRow(0)
        else:
            self.details.setPlainText(
                "No translations yet. "
                "Completed translations will appear here."
            )

    def display_item(self, row):
        if row < 0:
            return

        entry = list(reversed(self.entries))[row]

        self.details.setPlainText(
            f"{entry.get('source', '?')} → "
            f"{entry.get('target', '?')}\n\n"
            f"ORIGINAL\n"
            f"{entry.get('original', '')}\n\n"
            f"TRANSLATION\n"
            f"{entry.get('translated', '')}"
        )


class SettingsWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()

        self.controller = controller
        self.capturing = False

        self.setWindowTitle("EchoBridge — Settings")
        self.setMinimumSize(440, 570)
        self.resize(440, 570)

        from PySide6.QtWidgets import QTabWidget
        root = QTabWidget()
        root.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #303240; border-radius: 8px; }
            QTabBar::tab { background: #1C1E28; color: #B2B3C0; padding: 9px 22px; }
            QTabBar::tab:selected { background: #34304D; color: white; }
        """)
        self.setCentralWidget(root)
        general = QWidget()
        root.addTab(general, "General")
        from PySide6.QtWidgets import QScrollArea
        general_container = QVBoxLayout(general)
        general_container.setContentsMargins(0, 0, 0, 0)
        general_scroll = QScrollArea()
        general_scroll.setWidgetResizable(True)
        general_scroll.setFrameShape(QFrame.Shape.NoFrame)
        general_container.addWidget(general_scroll)
        general_content = QWidget()
        general_scroll.setWidget(general_content)
        layout = QVBoxLayout(general_content)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)

        title = QLabel("EchoBridge")
        title.setObjectName("title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Windows settings  ·  Runs in the system tray"
        )
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

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

        layout.addSpacing(8)

        layout.addWidget(
            self.heading("Push-to-Talk Key")
        )

        self.key_button = QPushButton(
            str(settings.value("hotkey", "F8"))
        )
        self.key_button.clicked.connect(
            self.start_capture
        )
        self.key_button.installEventFilter(self)
        layout.addWidget(self.key_button)

        layout.addWidget(
            self.heading("Input Microphone")
        )

        microphone_row = QHBoxLayout()
        self.microphone = NoWheelComboBox()
        microphone_row.addWidget(self.microphone, 1)
        self.mic_refresh = QPushButton("Refresh")
        self.mic_refresh.setObjectName("small")
        self.mic_refresh.clicked.connect(lambda: self.refresh_microphones(True))
        microphone_row.addWidget(self.mic_refresh)
        layout.addLayout(microphone_row)
        self.microphone_status = QLabel("Showing enabled Windows recording devices only.")
        self.microphone_status.setObjectName("muted")
        self.microphone_status.setWordWrap(True)
        layout.addWidget(self.microphone_status)
        self.microphone.currentIndexChanged.connect(self.microphone_changed)
        self.refresh_microphones()
        self.mic_feedback = QLabel("Last recording: not measured yet")
        self.mic_feedback.setObjectName("muted")
        self.mic_feedback.setWordWrap(True)
        layout.addWidget(self.mic_feedback)
        self.mic_meter = QProgressBar()
        self.mic_meter.setRange(0, 100)
        self.mic_meter.setValue(0)
        self.mic_meter.setTextVisible(False)
        self.mic_meter.setFixedHeight(12)
        self.mic_meter.setStyleSheet("QProgressBar { background: #292B36; border: 0; border-radius: 6px; } QProgressBar::chunk { background: #8175F5; border-radius: 6px; }")
        layout.addWidget(self.mic_meter)
        self.mic_test_button = QPushButton("Test Microphone")
        self.mic_test_button.clicked.connect(self.start_mic_test)
        layout.addWidget(self.mic_test_button)

        # Keep microphone hardware running and immediately gate audio on F8.
        # Opt-in only: Windows reports microphone usage while stream is active.
        self.instant_capture_toggle = QCheckBox(
            "Instant capture (no microphone startup delay when pressing F8)"
        )
        self.instant_capture_toggle.setChecked(
            settings.value('instant_capture', True, type=bool)
        )
        self.instant_capture_toggle.toggled.connect(self.change_instant_capture)
        layout.addWidget(self.instant_capture_toggle)
        instant_explanation = QLabel(
            "When enabled, EchoBridge keeps the microphone stream active while "
            "it runs. Windows may show the mic-in-use icon. Audio is discarded "
            "while idle; only F8 recordings are saved for transcription. "
            "Turn this off to release the microphone between recordings."
        )
        instant_explanation.setObjectName('muted')
        instant_explanation.setWordWrap(True)
        layout.addWidget(instant_explanation)

        self.mic_test = None
        self.mic_test_ticks = 0
        self.mic_test_timer = QTimer(self)
        self.mic_test_timer.setInterval(100)
        self.mic_test_timer.timeout.connect(self.update_mic_test)
        self.save_audio_btn = QPushButton("Save next recording to WAV (diagnostics)")
        self.save_audio_btn.clicked.connect(self.save_next_audio)
        layout.addWidget(self.save_audio_btn)
        self.audio_debug_label = QLabel("Optional: inspect the captured audio if recognition is wrong.")
        self.audio_debug_label.setWordWrap(True)
        self.audio_debug_label.setObjectName("muted")
        layout.addWidget(self.audio_debug_label)

        info = QLabel("Choose your spoken language, translation target, and offline packages in the Translations tab.")
        info.setObjectName("muted")
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addWidget(
            self.heading("Popup Auto-Close Delay")
        )

        self.timeout = QSpinBox()
        self.timeout.setRange(1, 300)
        self.timeout.setSuffix(" seconds")
        self.timeout.setValue(
            int(settings.value("popup_timeout", 10))
        )

        self.timeout.valueChanged.connect(
            lambda n: settings.setValue(
                "popup_timeout", n
            )
        )

        layout.addWidget(self.timeout)

        layout.addWidget(
            self.heading(
                "Popup Delay After Mouse Leaves"
            )
        )

        self.leave_timeout = QSpinBox()
        self.leave_timeout.setRange(1, 300)
        self.leave_timeout.setSuffix(" seconds")
        self.leave_timeout.setValue(
            int(settings.value(
                "popup_leave_timeout", 5
            ))
        )

        self.leave_timeout.valueChanged.connect(
            lambda n: settings.setValue(
                "popup_leave_timeout", n
            )
        )

        layout.addWidget(self.leave_timeout)

        hint = QLabel(
            "Hover over the popup to pause its timer.\n"
            "After leaving, a separate countdown begins."
        )
        hint.setObjectName("muted")
        layout.addWidget(hint)

        layout.addStretch()

        preview = QPushButton("Preview Popup")
        preview.setObjectName("primary")
        preview.clicked.connect(
            controller.preview
        )
        layout.addWidget(preview)

        footer = QLabel(
            "Hold your shortcut to record · Release to translate"
        )
        footer.setObjectName("muted")
        footer.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(footer)
        self.translation = TranslationSettingsPage(self)
        root.addTab(self.translation, "Translations")
        # Backward-compatible aliases for first-run wizard synchronization.
        self.speech_language = self.translation.speech_language
        self.language = self.translation.target
        self.ai_models = ModelSettingsPage(self)
        root.addTab(self.ai_models, "AI Models")
        self.tabs = root
        root.currentChanged.connect(
            lambda index: self.translation.refresh() if index == 1 else
            self.ai_models.refresh() if index == 2 else None
        )

    def change_instant_capture(self, enabled):
        runtime = getattr(self.controller, 'runtime', None)
        if runtime is None:
            settings.setValue('instant_capture', bool(enabled))
            return
        if not runtime.set_instant_capture(enabled):
            self.instant_capture_toggle.blockSignals(True)
            self.instant_capture_toggle.setChecked(runtime.recorder.instant_capture)
            self.instant_capture_toggle.blockSignals(False)
            self.mic_feedback.setText('Wait until the current recording or translation finishes.')
            return
        self.mic_feedback.setText(
            'Instant capture enabled. Windows may show the mic-in-use indicator.'
            if enabled else 'Instant capture disabled. Mic stream stops while idle.'
        )

    def start_mic_test(self):
        if self.mic_test is not None:
            self.stop_mic_test()
            return
        runtime = getattr(self.controller, "runtime", None)
        if runtime is not None and runtime.state != "idle":
            self.mic_feedback.setText("Finish recording or processing before testing the microphone.")
            return
        selected = self.microphone.currentData()
        if not selected:
            self.mic_feedback.setText("Select a microphone first.")
            return
        runtime = getattr(self.controller, "runtime", None)
        if runtime is not None:
            runtime.recorder.release()  # Let live mic test own the device.
        probe = MicrophoneTest(sd, str(selected), resolve_input)
        try:
            probe.start()
        except Exception as exc:
            self.mic_feedback.setText(f"Microphone test failed: {exc}")
            if runtime is not None:
                QTimer.singleShot(0, runtime.arm_microphone)
            return
        self.mic_test = probe
        self.mic_test_ticks = 0
        self.mic_meter.setValue(0)
        self.mic_test_button.setText("Stop Microphone Test")
        self.mic_feedback.setText(f"Testing {probe.device_name} — speak now...")
        self.mic_test_timer.start()

    def update_mic_test(self):
        probe = self.mic_test
        if probe is None:
            return
        self.mic_test_ticks += 1
        self.mic_meter.setValue(probe.level_percent())
        if probe.samples:
            self.mic_feedback.setText(f"Live input: {probe.device_name} · peak {probe.peak_db:.0f} dBFS")
        if self.mic_test_ticks >= 100:
            self.stop_mic_test()

    def stop_mic_test(self):
        # refresh_microphones() runs in __init__ before meter widgets exist.
        if not hasattr(self, "mic_test_timer"):
            return
        self.mic_test_timer.stop()
        probe = self.mic_test
        self.mic_test = None
        self.mic_test_button.setText("Test Microphone")
        self.mic_meter.setValue(0)
        if probe is None:
            return
        try:
            probe.stop()
        except Exception as exc:
            self.mic_feedback.setText(f"Microphone test error: {exc}")
            return
        runtime = getattr(self.controller, "runtime", None)
        if runtime is not None:
            QTimer.singleShot(0, runtime.arm_microphone)
        if not probe.samples:
            self.mic_feedback.setText("No audio frames received. Check Windows microphone access permissions.")
        elif probe.max_db < -55:
            self.mic_feedback.setText(f"No audible signal ({probe.max_db:.0f} dBFS) from {probe.device_name}. Check mute and Windows input volume.")
        else:
            self.mic_feedback.setText(f"Microphone working: {probe.device_name} · peak {probe.max_db:.0f} dBFS.")

    def microphone_changed(self, index):
        self.stop_mic_test()
        if index >= 0 and self.microphone.isEnabled():
            value = self.microphone.itemData(index)
            if value:
                settings.setValue("microphone", value)
                runtime = getattr(self.controller, "runtime", None)
                if runtime is not None and runtime.state == "idle":
                    QTimer.singleShot(0, runtime.arm_microphone)

    def refresh_microphones(self, reinitialize=False):
        self.stop_mic_test()
        # PortAudio caches the device list. Only reinitialize when idle; do not
        # interrupt a microphone stream that is currently recording.
        if reinitialize:
            runtime = getattr(self.controller, "runtime", None)
            if runtime is not None and runtime.state != "idle":
                self.microphone_status.setText("Finish the current recording before refreshing microphones.")
                return
            try:
                if hasattr(sd, "_terminate") and hasattr(sd, "_initialize"):
                    if runtime is not None:
                        runtime.recorder.release()
                    sd._terminate()
                    sd._initialize()
            except Exception as exc:
                self.microphone_status.setText(f"Could not refresh audio devices: {exc}")
                return

        saved = str(settings.value("microphone", "default"))
        self.microphone.blockSignals(True)
        self.microphone.clear()
        try:
            microphones = active_microphones(sd)
            if not microphones:
                self.microphone.addItem("No enabled microphones found", None)
                self.microphone.setEnabled(False)
                self.microphone_status.setText("Enable a microphone in Windows Sound settings, then click Refresh.")
                return
            self.microphone.addItem("Windows Default Microphone", "default")
            for mic in microphones:
                self.microphone.addItem(mic.label, mic.token)
            selected = normalize_selection(sd, saved)
            index = self.microphone.findData(selected)
            self.microphone.setCurrentIndex(max(index, 0))
            self.microphone.setEnabled(True)
            if selected != saved:
                settings.setValue("microphone", selected)
            self.microphone_status.setText(f"{len(microphones)} enabled microphone(s) detected.")
        except Exception as exc:
            self.microphone.addItem("Microphone list unavailable", None)
            self.microphone.setEnabled(False)
            self.microphone_status.setText(str(exc))
        finally:
            self.microphone.blockSignals(False)
            if reinitialize:
                runtime = getattr(self.controller, "runtime", None)
                if runtime is not None:
                    QTimer.singleShot(0, runtime.arm_microphone)

    def showEvent(self, event):
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

    def heading(self, title):
        label = QLabel(title)
        label.setObjectName("section")
        return label

    def save_next_audio(self):
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save the next recording (one time)",
            str(Path.home() / "EchoBridge-recording.wav"),
            "WAV audio (*.wav)"
        )
        if destination:
            settings.setValue("debug_next_wav_path", destination)
            self.audio_debug_label.setText("Next recording will also be saved to: " + destination)

    def show_mic_feedback(self, level, input_name=''):
        name = f"Input: {input_name} · " if input_name else ""
        self.mic_feedback.setText(
            f"{name}{level.seconds:.1f}s · "
            f"average {level.rms_dbfs:.0f} dBFS · "
            f"peak {level.peak_dbfs:.0f} dBFS"
        )

    def speech_language_changed(self):
        source = normalize_speech_language(self.speech_language.currentData())
        settings.setValue("speech_language", source)
        settings.sync()
        # Translation package selection is independent; never change it here.

    def start_capture(self):
        self.capturing = True
        self.controller.runtime.hotkey.set_suspended(True)
        self.key_button.setText(
            "Press a key (Esc cancels)"
        )
        self.key_button.setFocus()

    def eventFilter(self, obj, event):
        if (
            obj is self.key_button
            and self.capturing
            and event.type() == QEvent.Type.KeyPress
        ):
            if event.isAutoRepeat():
                return True

            if event.key() == Qt.Key.Key_Escape:
                self.key_button.setText(
                    str(settings.value("hotkey", "F8"))
                )
            else:
                combination = QKeySequence(
                    event.keyCombination()
                ).toString()

                if combination:
                    try:
                        self.controller.runtime.set_hotkey(combination)
                        self.key_button.setText(combination)
                    except ValueError as exc:
                        self.controller.runtime.notify_error(str(exc))
                        self.key_button.setText(str(settings.value("hotkey", "F8")))

            self.capturing = False
            self.controller.runtime.hotkey.set_suspended(False)
            return True

        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self.stop_mic_test()
        self.capturing = False
        self.controller.runtime.hotkey.set_suspended(False)
        if self.controller.quitting:
            event.accept()
        else:
            event.ignore()
            self.hide()


class EchoBridgeController:
    def __init__(self, app):
        self.app = app
        self.quitting = False
        self.popup = None
        self.history = self.load_history()

        self.window = SettingsWindow(self)
        self.indicator = StatusIndicator()

        self.tray = QSystemTrayIcon(
            app_icon(), app
        )
        self.tray.setToolTip(
            "EchoBridge — Ready"
        )

        menu = QMenu()
        menu.setObjectName("trayMenu")
        menu.setFixedWidth(220)
        menu.setStyleSheet("""
            QMenu#trayMenu {
                background-color: #191B25;
                color: #F0F0F5;
                border: 1px solid #343643;
                border-radius: 10px;
                padding: 6px 0px;
                font-family: 'Segoe UI';
                font-size: 12px;
            }

            QMenu#trayMenu::item {
                background: transparent;
                color: #F0F0F5;
                padding: 9px 18px;
                margin: 2px 6px;
                border-radius: 6px;
                min-height: 18px;
            }

            QMenu#trayMenu::item:selected {
                background-color: #34304D;
                color: #FFFFFF;
            }

            QMenu#trayMenu::separator {
                height: 1px;
                background: #343643;
                margin: 6px 14px;
            }
        """)

        settings_action = QAction(
            "Settings", menu
        )
        settings_action.triggered.connect(
            self.open_settings
        )
        menu.addAction(settings_action)

        setup_action = QAction("Setup Wizard...", menu)
        setup_action.triggered.connect(self.open_onboarding)
        menu.addAction(setup_action)

        recent_action = QAction(
            "Recent Translations", menu
        )
        recent_action.triggered.connect(
            self.open_history
        )
        menu.addAction(recent_action)

        menu.addSeparator()

        quit_action = QAction(
            "Quit EchoBridge", menu
        )
        quit_action.triggered.connect(
            self.quit
        )
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            self.tray_activated
        )
        self.tray.show()
        self.runtime = EchoBridgeRuntime(self)
        self.onboarding = None

        self.history_windows = []

        self.app.primaryScreenChanged.connect(
            lambda *_: self.reposition()
        )

        for screen in self.app.screens():
            screen.availableGeometryChanged.connect(
                lambda *_: self.reposition()
            )

        if not settings.value("onboarding_completed_v3", False, type=bool):
            QTimer.singleShot(0, self.open_onboarding)
        elif not QSystemTrayIcon.isSystemTrayAvailable():
            self.open_settings()

    def open_onboarding(self):
        if self.onboarding is not None and self.onboarding.isVisible():
            self.onboarding.raise_()
            self.onboarding.activateWindow()
            return
        self.runtime.hotkey.set_suspended(True)
        self.onboarding = FirstRunWizard(self)
        self.onboarding.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.onboarding.finished.connect(self.onboarding_finished)
        self.onboarding.show()
        self.onboarding.raise_()
        self.onboarding.activateWindow()

    def onboarding_finished(self, result):
        self.runtime.hotkey.set_suspended(False)
        self.onboarding = None

    def tray_activated(self, reason):
        if (
            reason ==
            QSystemTrayIcon.ActivationReason.DoubleClick
        ):
            self.open_settings()

    def open_settings(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def open_history(self):
        dialog = RecentTranslations(
            self.history
        )
        dialog.setAttribute(
            Qt.WidgetAttribute.WA_DeleteOnClose
        )

        self.history_windows.append(dialog)

        dialog.destroyed.connect(
            lambda: self.history_windows.remove(dialog)
            if dialog in self.history_windows else None
        )

        dialog.show()
        dialog.raise_()

    def reposition(self):
        corner_position(self.indicator)

        if self.popup:
            corner_position(
                self.popup, 16
            )

    def show_translation(
        self,
        original,
        translated,
        source="Auto-detected",
        target="English",
        save=True
    ):
        if save:
            self.history.append({
                "time": datetime.now().strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "source": source,
                "target": target,
                "original": original,
                "translated": translated
            })

            self.history = self.history[-50:]
            self.save_history()

        if self.popup:
            self.popup.close()

        self.popup = TranslationPopup(
            original,
            translated,
            source,
            target,
            settings.value(
                "popup_timeout", 10
            ),
            settings.value(
                "popup_leave_timeout", 5
            )
        )

    def preview(self):
        self.show_translation(
            "Cześć, jak się dzisiaj czujesz?",
            "Hi, how are you feeling today? "
            "(sample preview)",
            "Polish",
            "English · demo",
            save=False
        )

    def history_path(self):
        root = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )

        path = Path(root)
        path.mkdir(
            parents=True,
            exist_ok=True
        )

        return path / "history.json"

    def load_history(self):
        try:
            path = self.history_path()

            if path.exists():
                data = json.loads(
                    path.read_text(
                        encoding="utf-8"
                    )
                )

                return (
                    data[-50:]
                    if isinstance(data, list)
                    else []
                )

        except (OSError, ValueError):
            pass

        return []

    def save_history(self):
        try:
            self.history_path().write_text(
                json.dumps(
                    self.history,
                    ensure_ascii=False,
                    indent=2
                ),
                encoding="utf-8"
            )
        except OSError as exc:
            print(
                "Could not save translation history:",
                exc
            )

    def quit(self):
        if self.onboarding is not None and self.onboarding.job.running:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self.onboarding, 'EchoBridge', 'Finish the active setup download before quitting.')
            return
        self.quitting = True
        if self.onboarding is not None:
            self.onboarding.close()
        self.window.ai_models.stop_setup()
        self.window.translation.job.stop()
        self.runtime.shutdown()

        if self.popup:
            self.popup.close()

        self.indicator.close()
        self.window.close()

        for dialog in self.history_windows[:]:
            dialog.close()

        self.tray.hide()
        self.app.quit()


if __name__ == "__main__":
    if "--setup" in sys.argv:
        from echobridge_setup import main as setup_main
        sys.argv.remove("--setup")
        sys.exit(setup_main())
    if "--worker" in sys.argv:
        from echobridge_worker import main as worker_main
        sys.argv.remove("--worker")
        sys.exit(worker_main())
    app = QApplication(sys.argv)

    app.setApplicationName("EchoBridge")
    app.setOrganizationName("EchoBridge")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    app.setStyleSheet(STYLE)

    controller = EchoBridgeController(app)

    sys.exit(app.exec())
