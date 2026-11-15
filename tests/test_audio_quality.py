import numpy as np
import pytest
from echobridge_audio_quality import describe_pcm16, validate_pcm16


def test_speech_like_signal_passes():
    sample_rate = 16000
    time = np.arange(sample_rate * 2) / sample_rate
    audio = (np.sin(2 * np.pi * 200 * time) * 9000).astype(np.int16)
    level = validate_pcm16(audio, sample_rate)
    assert 1.99 < level.seconds < 2.01
    assert -25 < level.rms_dbfs < -5


def test_muted_microphone_is_rejected():
    with pytest.raises(ValueError, match='No usable microphone signal'):
        validate_pcm16(np.zeros(16000, dtype=np.int16), 16000)


def test_accidental_key_tap_is_rejected():
    with pytest.raises(ValueError, match='Recording too short'):
        validate_pcm16(np.ones(1600, dtype=np.int16) * 15000, 16000)


def test_near_silent_mic_is_rejected():
    with pytest.raises(ValueError, match='No usable microphone signal'):
        validate_pcm16(np.ones(16000, dtype=np.int16) * 4, 16000)
