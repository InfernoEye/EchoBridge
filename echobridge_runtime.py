"""Record speech on a Windows global hotkey; drive a disposable AI worker."""
import json
import os
import shutil
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, QProcess, QSettings, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import QSystemTrayIcon

from echobridge_hotkey import WindowsHotkey
from echobridge_models import ready_error
from echobridge_languages import language_display_name
from echobridge_audio_quality import validate_pcm16
from echobridge_microphones import resolve_input
from echobridge_capture import open_capture_stream, pcm16_from_float
from echobridge_preload import find_server, make_preload_spec
from echobridge_priority import lower_whisper_priority
from echobridge_gpus import selected_gpu_index
from echobridge_models import device_name, model_name, model_path, runtime_path


SETTINGS = QSettings("EchoBridge", "EchoBridge")
LANGUAGE_NAMES = {
    "en": "English", "pl": "Polish", "de": "German", "es": "Spanish",
    "fr": "French", "it": "Italian", "pt": "Portuguese", "uk": "Ukrainian",
    "ja": "Japanese", "zh": "Chinese", "ru": "Russian", "nl": "Dutch",
    "cs": "Czech", "tr": "Turkish", "sv": "Swedish", "ko": "Korean",
}


class Recorder:
    def __init__(self, instant_capture=False):
        # Instant mode keeps PortAudio active but drops ALL input while idle.
        # Windows will show the microphone as in use. It is strictly opt-in.
        self.instant_capture = bool(instant_capture)
        self.stream = None
        self.frames = []
        self.samples = 0
        self.rate = 0
        self.recording_error = ""
        self.last_level = None
        self.input_name = ""
        self.channels = 1
        self.last_warning = ""
        self.prepared_selection = None
        self.prepared_device_index = None
        self.recording = False

    def prepare(self, selected):
        """Open a stopped mic stream once, before the user's first hotkey.

        This keeps the input hardware configuration ready without continuously
        capturing or storing samples while idle. Whisper is not loaded here.
        """
        selected = str(selected or "default")
        if self.stream is not None and self.prepared_selection == selected:
            # An unexpected driver reset may have made a running stream inactive.
            # Re-arm it only when idle; the hotkey never waits for downloads.
            if self.instant_capture and not self.stream.active:
                self.stream.start()
            return
        self.release()
        index, device = resolve_input(sd, selected)
        self.input_name = str(device.get("name", "Unknown device"))

        def audio_callback(indata, frames, time_info, status):
            if not self.recording:
                return
            if status and not self.recording_error:
                self.recording_error = str(status)
            if self.samples < self.rate * 120:
                self.frames.append(indata.copy())
                self.samples += frames

        self.stream, self.channels, self.rate = open_capture_stream(
            sd, index, device, audio_callback, start=self.instant_capture
        )
        self.prepared_selection = selected
        self.prepared_device_index = index

    def start(self, selected):
        self.frames = []
        self.samples = 0
        self.recording_error = ""
        self.last_level = None
        self.prepare(selected)
        # Only start PortAudio capture on key-down. No stream construction,
        # device discovery, or format negotiation on the hotkey fast path.
        self.recording = True
        try:
            # In instant mode the stream is ALREADY active. Key-down only
            # enables the callback's in-memory recording gate (no driver call).
            if not self.stream.active:
                self.stream.start()
        except Exception:
            self.recording = False
            # Hardware may have been unplugged or reset while armed.
            # Discard stale stream; user may refresh devices in Settings.
            self.release()
            raise

    def stop(self):
        # Close the in-memory recording gate FIRST, before any UI or disk work.
        # Instant mode leaves PortAudio active but the callback drops all input.
        self.recording = False
        if self.stream and not self.instant_capture and self.stream.active:
            self.stream.stop()
        # Normal mode: open/stopped stream. Instant mode: active/discarding.
        # Neither mode saves audio while idle.
        # Keep usable audio even if PortAudio reports a transient overflow.
        self.last_warning = self.recording_error
        if not self.frames:
            raise RuntimeError("No microphone samples captured. Check the selected device.")
        with tempfile.NamedTemporaryFile(prefix="echobridge_", suffix=".wav", delete=False) as f:
            path = f.name
        try:
            with wave.open(path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                audio = pcm16_from_float(np.concatenate(self.frames, axis=0))
                if self.rate != 16000:
                    import math
                    try:
                        from scipy.signal import resample_poly
                        common = math.gcd(self.rate, 16000)
                        audio = resample_poly(audio.astype(np.float32), 16000 // common,
                                              self.rate // common)
                    except ImportError:
                        new_size = int(len(audio) * 16000 / self.rate)
                        audio = np.interp(np.linspace(0, len(audio) - 1, new_size),
                                          np.arange(len(audio)), audio.astype(np.float32))
                    audio = np.clip(np.round(audio), -32768, 32767).astype(np.int16)
                self.last_level = validate_pcm16(audio, 16000)
                wav.writeframes(audio.tobytes())
            return path
        except Exception:
            os.unlink(path)
            raise
        finally:
            self.frames.clear()
            self.samples = 0

    def release(self):
        """Fully close the prepared mic (device change, mic test, or quit)."""
        self.recording = False
        if self.stream:
            stream = self.stream
            self.stream = None
            try:
                if stream.active:
                    stream.abort()
            finally:
                stream.close()
        self.prepared_selection = None
        self.prepared_device_index = None

    def abort(self):
        self.release()
        self.frames.clear()
        self.samples = 0


class EchoBridgeRuntime(QObject):
    def __init__(self, controller):
        super().__init__(controller.app)
        self.controller = controller
        self.recorder = Recorder(
            instant_capture=SETTINGS.value('instant_capture', True, type=bool)
        )
        self.state = "idle"
        self.worker = None
        self.worker_ready = False
        self.preload = None
        self.preload_spec = None
        self.preload_ready = False
        self.preload_started_at = None
        self.preload_error = ''
        self.preload_output = b''
        self.probe_inflight = False
        self.network = QNetworkAccessManager(self)
        self.probe_timer = QTimer(self)
        self.probe_timer.setInterval(350)
        self.probe_timer.timeout.connect(self.check_preload_ready)
        self.audio_path = None
        self.buffer = b""
        self.result = None
        self.error_text = None
        try:
            self.hotkey = WindowsHotkey(str(SETTINGS.value("hotkey", "F8")), self)
        except ValueError:
            SETTINGS.setValue("hotkey", "F8")
            self.hotkey = WindowsHotkey("F8", self)
        self.hotkey.pressed.connect(self.on_pressed)
        self.hotkey.released.connect(self.on_released)
        self.hotkey.error.connect(self.notify_error)
        self.hotkey.start()
        self.max_recording = QTimer(self)
        self.max_recording.setSingleShot(True)
        self.max_recording.timeout.connect(self.on_released)
        # Prepare a stopped microphone as soon as the Qt event loop starts.
        # Model memory remains unloaded until a recording begins.
        QTimer.singleShot(0, self.arm_microphone)

    def arm_microphone(self):
        if self.state != "idle":
            return
        # The microphone test (also in the first-run wizard) owns its stream.
        if getattr(self.controller.window, "mic_test", None) is not None:
            return
        onboarding = getattr(self.controller, 'onboarding', None)
        if onboarding is not None and getattr(onboarding, 'test', None) is not None:
            return
        try:
            selected = str(SETTINGS.value("microphone", "default"))
            started = time.perf_counter()
            self.recorder.prepare(selected)
            print(f"[EchoBridge timing] microphone armed in "
                  f"{(time.perf_counter() - started) * 1000:.0f} ms", flush=True)
        except Exception as exc:
            print(f"[EchoBridge microphone] could not pre-arm: {exc}", flush=True)
            # Hotkey will retry and show a visible error if necessary.

    def set_instant_capture(self, enabled):
        """Change stream policy while idle; never reconfigure during recording."""
        if self.state != 'idle':
            return False
        enabled = bool(enabled)
        if self.recorder.instant_capture != enabled:
            self.recorder.release()
            self.recorder.instant_capture = enabled
        SETTINGS.setValue('instant_capture', enabled)
        QTimer.singleShot(0, self.arm_microphone)
        return True

    def set_hotkey(self, shortcut):
        self.hotkey.set_hotkey(shortcut)
        SETTINGS.setValue("hotkey", shortcut)

    def notify_error(self, message):
        self.controller.tray.showMessage("EchoBridge", message,
                                         QSystemTrayIcon.MessageIcon.Warning, 7000)
        self.controller.tray.setToolTip("EchoBridge — Error")

    def on_pressed(self):
        if self.state != "idle":
            return
        pressed_at = time.perf_counter()
        keydown_ns = getattr(self.hotkey, 'last_pressed_ns', 0)
        self.state = "recording"
        self.worker_ready = False
        self.audio_path = None
        self.result = None
        self.error_text = None
        self.buffer = b""

        # CRITICAL: first capture, THEN check AI files, display UI or load model.
        # In instant mode this flips a boolean on an already-running input
        # callback; normal mode must still start the stopped Windows stream.
        try:
            if getattr(self.controller.window, 'mic_test', None) is not None:
                self.controller.window.stop_mic_test()
            self.recorder.start(str(SETTINGS.value("microphone", "default")))
        except Exception as exc:
            self.state = "idle"
            self.controller.indicator.set_status("")
            self.controller.window.mic_feedback.setText(f"Recording failed: {exc}")
            self.notify_error(f"Could not start recording: {exc}")
            QTimer.singleShot(0, self.arm_microphone)
            return

        active_ns = time.perf_counter_ns()
        handler_ms = (time.perf_counter() - pressed_at) * 1000
        from_key_ms = ((active_ns - keydown_ns) / 1e6) if keydown_ns else handler_ms
        print(f'[EchoBridge timing] keydown-to-capture {from_key_ms:.1f} ms '
              f'(handler {handler_ms:.1f} ms; instant={self.recorder.instant_capture})',
              flush=True)
        self.controller.indicator.set_status("●  Listening...")
        self.controller.tray.setToolTip("EchoBridge — Listening")
        self.max_recording.start(120000)

        # Check installation AFTER capture starts. If setup is incomplete,
        # stop this attempt and show the user exactly what is missing.
        unavailable = ready_error()
        if unavailable:
            self.max_recording.stop()
            self.recorder.abort()
            self.state = 'idle'
            self.controller.indicator.set_status('')
            self.notify_error(unavailable)
            QTimer.singleShot(0, self.arm_microphone)
            return
        self.start_preload()

    def start_preload(self):
        # Start immediately after mic activation, while the user is speaking.
        # No Whisper model is kept in memory between recordings.
        self.stop_preload()
        self.preload_ready = False
        self.preload_error = ''
        self.preload_output = b''
        cli = runtime_path()
        server = find_server(cli)
        if not server:
            self.preload_error = 'Preload server not installed (reinstall the runtime in Speech Models)'
            print('[EchoBridge preload] ' + self.preload_error, flush=True)
            return
        try:
            backend = device_name()
            index = selected_gpu_index(SETTINGS, backend) if backend != 'cpu' else 0
            spec = make_preload_spec(
                server, model_path(model_name()), backend,
                index, source=str(SETTINGS.value('speech_language', 'auto')))
            process = QProcess(self)
            process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.preload = process
            self.preload_spec = spec
            self.preload_started_at = time.perf_counter()
            process.started.connect(lambda: self.preload_started(process))
            process.readyReadStandardOutput.connect(self.read_preload_output)
            process.errorOccurred.connect(self.preload_process_error)
            process.finished.connect(self.preload_process_finished)
            process.start(spec.program, list(spec.args))
            self.controller.tray.setToolTip('EchoBridge — Listening; loading Whisper in background')
            self.controller.indicator.set_status('● Listening · AI loading')
            print(f'[EchoBridge preload] launched whisper-server at F8 press '
                  f'({spec.program})', flush=True)
        except Exception as exc:
            self.preload_error = str(exc)
            self.preload_spec = None
            self.controller.tray.setToolTip('EchoBridge — Whisper preloading unavailable')
            print(f'[EchoBridge preload] startup failed: {exc}', flush=True)

    def preload_started(self, process):
        if process is self.preload:
            lower_whisper_priority(int(process.processId()))
            self.probe_timer.start()

    def read_preload_output(self):
        if self.preload:
            self.preload_output = (self.preload_output +
                                   bytes(self.preload.readAllStandardOutput()))[-3500:]

    def preload_process_error(self, error):
        if self.preload is not None:
            self.preload_error = f'Windows could not launch the model server ({error})'
            self.probe_timer.stop()
            print('[EchoBridge preload] ' + self.preload_error, flush=True)

    def preload_process_finished(self, code, status):
        if self.preload is None:
            return
        self.read_preload_output()
        if self.preload_spec and not self.preload_ready:
            self.preload_error = (f'Whisper server stopped before model was ready (exit {code}). '
                                  + self.preload_output.decode('utf-8', 'replace')[-350:])
            self.probe_timer.stop()
            print('[EchoBridge preload] ' + self.preload_error, flush=True)
            if self.state == 'recording':
                self.controller.indicator.set_status('● Listening · AI fallback')

    def check_preload_ready(self):
        if (not self.preload_spec or not self.preload or self.preload_ready
                or self.probe_inflight or self.preload.state() == QProcess.ProcessState.NotRunning):
            return
        spec = self.preload_spec
        url = QUrl(f'http://127.0.0.1:{spec.port}{spec.request_path}/')
        self.probe_inflight = True
        reply = self.network.get(QNetworkRequest(url))
        reply.finished.connect(lambda: self.preload_probe_result(reply, spec))

    def preload_probe_result(self, reply, spec):
        try:
            ok = (reply.error() == QNetworkReply.NetworkError.NoError and
                  int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0) == 200)
            if ok and spec is self.preload_spec and self.preload is not None:
                self.preload_ready = True
                self.probe_timer.stop()
                elapsed = (time.perf_counter() - self.preload_started_at) if self.preload_started_at else 0
                print(f'[EchoBridge preload] Whisper model READY {elapsed:.1f}s after key-down', flush=True)
                if self.state == 'recording':
                    self.controller.indicator.set_status('● Listening · AI ready')
                elif self.state == 'processing':
                    self.controller.indicator.set_status('◌ Transcribing...')
        finally:
            self.probe_inflight = False
            reply.deleteLater()

    def stop_preload(self):
        self.probe_timer.stop()
        self.preload_spec = None
        self.preload_ready = False
        self.probe_inflight = False
        if self.preload:
            process = self.preload
            self.preload = None
            if process.state() != QProcess.ProcessState.NotRunning:
                process.finished.connect(process.deleteLater)
                process.kill()
            else:
                process.deleteLater()

    def start_inference_worker(self):
        # Avoid CPU contention during microphone capture.
        self.worker = QProcess(self)
        self.worker.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.worker.readyReadStandardOutput.connect(self.read_worker)
        self.worker.readyReadStandardError.connect(self.read_errors)
        self.worker.errorOccurred.connect(self.process_error)
        self.worker.finished.connect(self.process_finished)
        target = str(SETTINGS.value("language", "en"))
        source = str(SETTINGS.value("speech_language", "auto"))
        options = ["--source", source, "--target", target]
        if self.preload_spec and self.preload and self.preload.state() != QProcess.ProcessState.NotRunning:
            options.extend(["--warm-port", str(self.preload_spec.port),
                            "--warm-path", self.preload_spec.request_path,
                            "--warm-pid", str(self.preload.processId())])
        else:
            detail = self.preload_error or 'Whisper preload not available'
            print(f'[EchoBridge preload] CLI fallback: {detail}', flush=True)
            self.controller.indicator.set_status('◌ Loading Whisper (fallback)...')
        if getattr(sys, "frozen", False):
            self.worker.start(sys.executable, ["--worker", *options])
        else:
            worker_py = str(Path(__file__).with_name("echobridge_worker.py"))
            self.worker.start(sys.executable, ["-u", worker_py, *options])

    def on_released(self):
        if self.state != "recording":
            return
        self.max_recording.stop()
        # Stop collecting samples before repainting the indicator or writing WAV.
        self.recorder.recording = False
        self.state = "processing"
        self.controller.indicator.set_status(
            '◌ Transcribing...' if self.preload_ready else
            '◌ Loading Whisper...' if self.preload_spec else
            '◌ Loading Whisper (fallback)...')
        self.controller.tray.setToolTip("EchoBridge — Processing")
        try:
            self.audio_path = self.recorder.stop()
        except Exception as exc:
            self.error_text = str(exc)
            self.controller.window.mic_feedback.setText(f"Recording failed: {exc}")
            if self.worker and self.worker.state() != QProcess.ProcessState.NotRunning:
                self.worker.kill()
            else:
                self.complete()
            self.stop_preload()
            return
        if self.recorder.last_level:
            level = self.recorder.last_level
            self.controller.window.show_mic_feedback(level, self.recorder.input_name)
        # One-time, user-initiated microphone recording export for debugging.
        save_to = str(SETTINGS.value('debug_next_wav_path', '') or '').strip()
        if save_to:
            SETTINGS.remove('debug_next_wav_path')
            SETTINGS.sync()
            try:
                shutil.copyfile(self.audio_path, save_to)
                self.controller.window.audio_debug_label.setText(
                    f'Diagnostic audio saved to: {save_to}'
                )
            except OSError as exc:
                self.notify_error(f'Could not save diagnostic WAV: {exc}')
        self.start_inference_worker()

    def deliver_audio(self):
        if (not self.worker_ready or not self.audio_path or not self.worker or
                self.worker.state() != QProcess.ProcessState.Running):
            return
        payload = json.dumps({"audio": self.audio_path}).encode("utf-8") + b"\n"
        self.worker.write(payload)
        self.worker.closeWriteChannel()
        self.worker_ready = False

    def read_worker(self):
        if not self.worker:
            return
        self.buffer += bytes(self.worker.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            kind = event.get("event")
            if kind == "ready":
                self.worker_ready = True
                self.deliver_audio()
            elif kind == "phase":
                phase = str(event.get("name", "Processing"))
                self.controller.tray.setToolTip("EchoBridge — " + phase)
                if self.state == "processing":
                    label = ("◌  Translating..." if "translat" in phase.lower() else
                             "◌  Loading Whisper..." if "loading" in phase.lower() else
                             "◌  Transcribing...")
                    self.controller.indicator.set_status(label)
            elif kind == "result":
                self.result = event
            elif kind == "error":
                self.error_text = event.get("message") or "Processing failed"
                if event.get("original"):
                    self.result = event

    def read_errors(self):
        if self.worker:
            # Keep a limited diagnostic tail without displaying raw process output.
            self.stderr_tail = (getattr(self, "stderr_tail", b"") +
                                bytes(self.worker.readAllStandardError()))[-3000:]

    def process_error(self, error):
        if not self.error_text:
            self.error_text = f"Could not launch speech worker ({error})"
        if self.worker and self.worker.state() == QProcess.ProcessState.NotRunning:
            QTimer.singleShot(0, self.complete)

    def process_finished(self, code, status):
        self.read_worker()
        self.read_errors()
        self.complete()

    def complete(self):
        self.stop_preload()
        if self.audio_path:
            try:
                os.unlink(self.audio_path)
            except OSError:
                pass
            self.audio_path = None
        if self.state == "recording":
            self.recorder.abort()
            self.controller.indicator.set_status("")
        result = self.result
        error = self.error_text
        self.max_recording.stop()
        self.controller.indicator.set_status("")
        self.state = "idle"
        self.controller.tray.setToolTip("EchoBridge — Ready")
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        if result and result.get("event") == "result":
            source = language_display_name(result["source"])
            target = language_display_name(result["target"])
            self.controller.show_translation(result["original"], result["translated"],
                                             source, target, save=True)
        elif result and result.get("original"):
            source = language_display_name(result.get("source", ""))
            target = language_display_name(result.get("target", ""))
            self.controller.show_translation(result["original"],
                                             f"Translation failed: {error}",
                                             source, target, save=False)
        elif error:
            self.notify_error(error)
        else:
            self.notify_error("The speech worker stopped unexpectedly.")

    def shutdown(self):
        self.max_recording.stop()
        self.stop_preload()
        self.hotkey.stop()
        self.recorder.abort()
        self.controller.indicator.set_status("")
        if self.worker:
            try:
                self.worker.finished.disconnect(self.process_finished)
                self.worker.errorOccurred.disconnect(self.process_error)
            except (RuntimeError, TypeError):
                pass
            self.worker.kill()
            self.worker.waitForFinished(1200)
        if self.audio_path:
            try:
                os.unlink(self.audio_path)
            except OSError:
                pass
