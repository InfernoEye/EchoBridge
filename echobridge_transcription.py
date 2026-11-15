"""whisper.cpp command construction, isolated for testing."""


def build_command(cli, model, wav, language, prefix, backend, gpu_index=0,
                  supported=(), vad_model=None):
    args = [str(cli), '-m', str(model), '-f', str(wav), '-l', language,
            '-oj', '-of', str(prefix), '-nt', '-bs', '5']
    if backend == 'cpu':
        args.append('-ng')
    else:
        args.extend(['-dev', str(max(0, int(gpu_index)))])
    if '--no-fallback' in supported:
        args.append('-nf')
    if '--suppress-nst' in supported:
        args.append('-sns')
    if vad_model is not None and '--vad' in supported and '--vad-model' in supported:
        args.extend(['--vad', '--vad-model', str(vad_model)])
        if '--vad-speech-pad-ms' in supported:
            # More padding preserves word boundaries for longer recordings.
            args.extend(['--vad-speech-pad-ms', '350'])
    return args


def vad_for_duration(seconds, vad_installed, minimum=8.0):
    """Do not trim short push-to-talk speech; optional VAD on long dictation."""
    return bool(vad_installed) and float(seconds) >= float(minimum)
