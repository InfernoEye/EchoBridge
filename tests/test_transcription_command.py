from echobridge_transcription import build_command


def test_cpu_auto_and_hallucination_flags():
    cmd = build_command('whisper-cli.exe', 'small.bin', 'clip.wav', 'auto',
                        'result', 'cpu', supported={'--no-fallback', '--suppress-nst'})
    assert cmd[cmd.index('-l') + 1] == 'auto'
    assert '-ng' in cmd
    assert '-nf' in cmd and '-sns' in cmd
    assert '--vad' not in cmd


def test_manual_language_and_gpu():
    cmd = build_command('whisper-cli.exe', 'large-v3.bin', 'clip.wav', 'pl',
                        'result', 'nvidia', gpu_index=2)
    assert cmd[cmd.index('-l') + 1] == 'pl'
    assert cmd[cmd.index('-dev') + 1] == '2'
    assert '-ng' not in cmd


def test_vad_only_when_binary_supports_it():
    cmd = build_command('cli', 'm', 'a', 'pl', 'out', 'cpu',
                        supported={'--vad'}, vad_model='silero.bin')
    assert '--vad' not in cmd
    cmd = build_command('cli', 'm', 'a', 'pl', 'out', 'cpu',
                        supported={'--vad', '--vad-model', '--vad-speech-pad-ms'},
                        vad_model='silero.bin')
    assert '--vad' in cmd
    assert cmd[cmd.index('--vad-model') + 1] == 'silero.bin'
    assert cmd[cmd.index('--vad-speech-pad-ms') + 1] == '350'


def test_short_clip_disables_vad_to_preserve_first_words():
    from echobridge_transcription import vad_for_duration
    assert not vad_for_duration(1.5, True)
    assert not vad_for_duration(7.9, True)
    assert vad_for_duration(8.1, True)
    assert not vad_for_duration(15, False)
