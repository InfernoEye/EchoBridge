"""Reliable input capture shared by recording and the Settings mic test.

Input devices are already filtered by echobridge_microphones. We use native
sample rates and capture up to two channels to avoid silently reading an empty
mono channel from some Windows microphone arrays.
"""
from __future__ import annotations

import math
import numpy as np


def stream_candidates(device):
    max_channels = max(1, int(device.get('max_input_channels') or 1))
    channels = list(dict.fromkeys([min(2, max_channels), 1]))
    default_rate = int(round(float(device.get('default_samplerate') or 48000)))
    rates = list(dict.fromkeys([default_rate, 48000, 44100, 16000]))
    return [(channels_count, rate) for channels_count in channels for rate in rates]


def open_capture_stream(sd, index, device, callback, start=True):
    """Open shared input with first working supported configuration.

    Never switch to a different physical device implicitly.  PortAudio check
    alone is insufficient: an input may be busy/permission denied at open time.
    """
    failures = []
    for channels, rate in stream_candidates(device):
        for latency in ('low', 'high'):
            stream = None
            try:
                # InputStream itself validates format support. A separate
                # check_input_settings call adds latency to the hotkey path.
                stream = sd.InputStream(device=index, channels=channels,
                                        samplerate=rate, dtype='float32',
                                        latency=latency, callback=callback)
                # When start=False, reserve/prepare the device but DO NOT
                # start capturing until the user presses the hotkey.
                if start:
                    stream.start()
                return stream, channels, rate
            except Exception as exc:
                failures.append(f'{channels}ch/{rate}Hz ({latency}): {exc}')
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
    detail = '; '.join(failures[:3])
    raise RuntimeError(
        f'Unable to open the selected Windows microphone ({device.get("name", "unknown")}). '
        f'Check Windows microphone access, default audio format, and whether another app holds it. '
        f'Tried {len(failures)} input formats. {detail}'
    )


def strongest_channel(multi_channel_float_audio):
    """Select the channel with most energy (avoid silent left/right channels)."""
    audio = np.asarray(multi_channel_float_audio, dtype=np.float32)
    if audio.ndim == 1:
        return audio
    if audio.ndim != 2 or audio.shape[1] < 1:
        raise ValueError('Invalid captured audio channel shape')
    energy = np.mean(np.square(audio.astype(np.float64)), axis=0)
    return np.ascontiguousarray(audio[:, int(np.argmax(energy))])


def pcm16_from_float(frames):
    mono = strongest_channel(frames)
    return np.rint(np.clip(mono, -1.0, 1.0) * 32767.0).astype(np.int16)


class MicrophoneTest:
    """Short live audio test. No AI model, history entry, or saved recording."""

    def __init__(self, sd, selection, resolve_input):
        self.sd = sd
        self.selection = selection
        self.resolve_input = resolve_input
        self.stream = None
        self.device_name = ''
        self.rate = 0
        self.channels = 0
        self.samples = 0
        self.max_peak = 0.0
        self.last_peak = 0.0
        self.last_rms = 0.0
        self.warnings = []

    def start(self):
        index, device = self.resolve_input(self.sd, self.selection)
        self.device_name = str(device.get('name') or 'Microphone')

        def callback(indata, frames, time_info, status):
            if status and len(self.warnings) < 5:
                self.warnings.append(str(status))
            signal = strongest_channel(indata)
            if signal.size:
                self.last_peak = float(np.max(np.abs(signal)))
                self.max_peak = max(self.max_peak, self.last_peak)
                self.last_rms = float(np.sqrt(np.mean(np.square(signal.astype(np.float64)))))
                self.samples += frames

        self.stream, self.channels, self.rate = open_capture_stream(
            self.sd, index, device, callback
        )

    def stop(self):
        stream = self.stream
        self.stream = None
        if stream:
            try:
                stream.stop()
            finally:
                stream.close()

    @property
    def peak_db(self):
        return 20.0 * math.log10(max(self.last_peak, 1e-8))

    @property
    def max_db(self):
        return 20.0 * math.log10(max(self.max_peak, 1e-8))

    def level_percent(self):
        # Human-friendly meter: -60 dB = 0%, -6 dB = 100%.
        return int(max(0, min(100, (self.peak_db + 60.0) * 100.0 / 54.0)))
