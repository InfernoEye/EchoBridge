"""Cheap PCM16 microphone sanity checks, without loading any AI models.

Conservative: reject only recordings that are almost certainly silent. Levels
cannot prove that meaningful speech exists; that requires speech detection.
"""
import math
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class AudioLevel:
    seconds: float
    rms_dbfs: float
    peak_dbfs: float
    clipped_percent: float


def describe_pcm16(samples, sample_rate):
    pcm = np.asarray(samples, dtype=np.int16).reshape(-1)
    if sample_rate <= 0 or not len(pcm):
        raise ValueError('No audio was captured from the microphone.')
    audio = pcm.astype(np.float64) / 32768.0
    rms = float(np.sqrt(np.mean(audio * audio)))
    peak = float(np.max(np.abs(audio)))
    clipped_percent = 100 * float(np.count_nonzero(np.abs(audio) >= 0.999)) / len(audio)
    to_db = lambda value: 20 * math.log10(max(value, 1e-12))
    return AudioLevel(len(pcm) / sample_rate, to_db(rms), to_db(peak), clipped_percent)


def validate_pcm16(samples, sample_rate):
    level = describe_pcm16(samples, sample_rate)
    if level.seconds < 0.35:
        raise ValueError('Recording too short. Hold the key and speak for longer.')
    # Do not guess transcript content from a dead or muted mic.
    if level.peak_dbfs < -55 and level.rms_dbfs < -62:
        raise ValueError(
            'No usable microphone signal. Check the selected input device, '
            'microphone permissions and input volume.'
        )
    return level
