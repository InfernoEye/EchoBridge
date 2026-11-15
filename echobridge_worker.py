"""One-recording worker. No downloads; whisper-cli exits and frees its model memory."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from echobridge_models import device_name, model_name, model_path, runtime_path, model_ready, vad_ready, VAD_PATH
from echobridge_transcription import build_command, vad_for_duration
from echobridge_gpus import selected_gpu_index
from echobridge_translation_routes import plan_translation
from echobridge_server_client import transcribe_preloaded


def send(event, **values):
    print(json.dumps({'event': event, **values}, ensure_ascii=True), flush=True)


def translate_text(text, source, target):
    if source == target:
        return text
    import argostranslate.package as package
    import argostranslate.translate as translate
    installed = {(p.from_code, p.to_code) for p in package.get_installed_packages()}
    try:
        route = plan_translation(source, target, installed)
    except RuntimeError as exc:
        raise RuntimeError(
            f'No installed offline route for {source} → {target}. '
            'Open Settings → AI Models, choose that language pair and install it.'
        ) from exc
    for from_lang, to_lang in route:
        text = translate.translate(text, from_lang, to_lang)
    return text



def supported_features(cli):
    # A currently installed CPU or GPU binary may be a different whisper.cpp version.
    # Query the actual CLI so optional anti-hallucination and VAD flags never break it.
    opts = {'capture_output': True, 'text': True, 'encoding': 'utf-8',
            'errors': 'replace', 'timeout': 12}
    if sys.platform == 'win32':
        opts['creationflags'] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run([str(cli), '--help'], **opts)
        output = (proc.stdout or '') + '\n' + (proc.stderr or '')
    except (OSError, subprocess.TimeoutExpired):
        return set()
    candidates = ('--vad', '--vad-model', '--vad-speech-pad-ms',
                  '--no-fallback', '--suppress-nst')
    return {x for x in candidates if x in output}


def transcribe(wav, speech_language='auto'):
    from echobridge_languages import normalize_speech_language
    speech_language = normalize_speech_language(speech_language)
    selected = model_name()
    backend = device_name()
    model = model_path(selected)
    cli = runtime_path(backend)
    if not model_ready(selected):
        raise RuntimeError(f'Whisper model {selected} is not installed or incomplete. Use Settings → AI Models.')
    if not cli:
        raise RuntimeError(f'{backend.upper()} runtime not installed. Use Settings → AI Models.')
    send('phase', name='Transcribing')
    with tempfile.TemporaryDirectory(prefix='echobridge_result_') as tmp:
        prefix = str(Path(tmp) / 'speech')
        from PySide6.QtCore import QSettings
        settings = QSettings('EchoBridge', 'EchoBridge')
        features = supported_features(cli)
        if vad_ready() and not {'--vad', '--vad-model'}.issubset(features):
            send('phase', name='Runtime does not support installed speech detector')
        import wave
        with wave.open(str(wav), 'rb') as audio:
            seconds = audio.getnframes() / max(1, audio.getframerate())
        args = build_command(
            cli, model, wav, speech_language, prefix, backend,
            gpu_index=selected_gpu_index(settings, backend),
            supported=features,
            vad_model=VAD_PATH if vad_for_duration(seconds, vad_ready()) else None
        )
        run_options = {'capture_output': True, 'text': True, 'encoding': 'utf-8', 'errors': 'replace'}
        if sys.platform == 'win32':
            run_options['creationflags'] = subprocess.CREATE_NO_WINDOW
        outcome = subprocess.run(args, **run_options)
        if outcome.returncode:
            tail = (outcome.stderr or outcome.stdout or '').strip()[-1100:]
            raise RuntimeError(f'Whisper processing failed: {tail}')
        result_file = Path(prefix + '.json')
        if not result_file.is_file():
            raise RuntimeError('Whisper did not produce a transcription JSON file.')
        raw = json.loads(result_file.read_text(encoding='utf-8-sig'))
        language = (speech_language if speech_language != 'auto' else
                    str(raw.get('result', {}).get('language') or '').lower())
        original = ' '.join(str(item.get('text', '')).strip()
                            for item in raw.get('transcription', [])).strip()
        if not language or language == 'auto':
            raise RuntimeError('Whisper could not detect the spoken language.')
        if not original:
            raise RuntimeError('No speech detected. Try a longer recording.')
        return original, language


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='auto')
    parser.add_argument('--target', default='en')
    parser.add_argument('--warm-port', type=int)
    parser.add_argument('--warm-path')
    parser.add_argument('--warm-pid', type=int)
    args = parser.parse_args()
    original, source = '', ''
    try:
        send('ready')
        command = json.loads(sys.stdin.readline())
        if args.warm_port and args.warm_path:
            try:
                send('phase', name='Using Whisper model started during recording')
                original, source = transcribe_preloaded(command['audio'], args.source,
                                                        args.warm_port, args.warm_path,
                                                        args.warm_pid)
            except (OSError, RuntimeError, TimeoutError) as exc:
                # Only fall back if the server couldn't start/reply. A real
                # empty-transcription response is reported, not retried.
                if 'did not detect speech' in str(exc).lower():
                    raise
                send('phase', name=f'Preload failed ({str(exc)[:160]}); loading Whisper CLI instead')
                original, source = transcribe(command['audio'], args.source)
        else:
            original, source = transcribe(command['audio'], args.source)
        send('phase', name='Translating')
        translated = translate_text(original, source, args.target)
        send('result', original=original, translated=translated, source=source, target=args.target)
        return 0
    except Exception as exc:
        send('error', message=str(exc), original=original, source=source, target=args.target)
        return 1

if __name__ == '__main__':
    sys.exit(main())
