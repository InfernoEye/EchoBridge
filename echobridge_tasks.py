"""Shared nonblocking progress and lifecycle for model/translation setup jobs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class SetupTask(QObject):
    progress = Signal(int)
    phase = Signal(str)
    finished = Signal(bool, str)
    runningChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.stdout = b''
        self.stderr = b''
        self.error = ''
        self.done = False
        self.description = ''

    @property
    def running(self):
        return self.process is not None

    def start(self, arguments, description):
        if self.running:
            raise RuntimeError('A download or removal is already running')
        self.stdout = self.stderr = b''
        self.error = ''
        self.done = False
        self.description = description
        self.phase.emit(f'Starting {description} ...')
        self.progress.emit(-1)
        process = QProcess(self)
        self.process = process
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read)
        process.readyReadStandardError.connect(self._read_error)
        process.finished.connect(self._completed)
        process.errorOccurred.connect(self._failed)
        if getattr(sys, 'frozen', False):
            process.start(sys.executable, ['--setup', *arguments])
        else:
            process.start(sys.executable, ['-u', str(Path(__file__).with_name('echobridge_setup.py')), *arguments])
        self.runningChanged.emit(True)

    def _read(self):
        if not self.process:
            return
        self.stdout += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.stdout:
            line, self.stdout = self.stdout.split(b'\n', 1)
            try:
                event = json.loads(line.decode('utf-8'))
            except (UnicodeError, ValueError):
                continue
            kind = event.get('event')
            if kind == 'progress':
                self.progress.emit(max(0, min(100, int(event.get('percent', 0)))))
            elif kind in ('phase', 'component'):
                self.phase.emit(str(event.get('message', 'Installing...')))
                self.progress.emit(-1)
            elif kind == 'done':
                self.done = True
                self.phase.emit(str(event.get('message', 'Installed successfully')))
            elif kind == 'error':
                self.error = str(event.get('message', 'Unknown installation error'))
                self.phase.emit(self.error)

    def _read_error(self):
        if self.process:
            self.stderr = (self.stderr + bytes(self.process.readAllStandardError()))[-4000:]

    def _failed(self, error):
        self.error = self.error or f'Failed to start setup worker: {error}'
        # Qt may emit FailedToStart without a later finished event.
        if self.process and error == QProcess.ProcessError.FailedToStart:
            QTimer.singleShot(0, lambda: self._completed(1, QProcess.ExitStatus.CrashExit)
                              if self.process else None)

    def _completed(self, code, status):
        self._read()
        self._read_error()
        success = code == 0 and self.done and not self.error
        msg = ('Completed successfully' if success else
               self.error or self.stderr.decode('utf-8', 'replace')[-700:] or
               f'Operation exited with status {code}')
        proc = self.process
        self.process = None
        if proc:
            proc.deleteLater()
        self.progress.emit(100 if success else 0)
        self.runningChanged.emit(False)
        self.finished.emit(success, msg)

    def stop(self):
        if self.process:
            self.process.kill()
            self.process.waitForFinished(2000)
