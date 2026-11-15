"""Local HTTP client for a short-lived whisper.cpp server.

No microphone data is sent to the internet. The server listens on loopback,
uses a per-recording unguessable request path, and is terminated by the host.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from echobridge_languages import SPEECH_LANGUAGES, normalize_speech_language

_LANGUAGE_BY_NAME = {name.casefold(): code for code, name in SPEECH_LANGUAGES}


def whisper_language_code(value):
    """Server verbose JSON uses full names; CLI JSON often uses ISO codes."""
    original = str(value or '').strip()
    code = normalize_speech_language(original)
    if code != 'auto':
        return code
    return _LANGUAGE_BY_NAME.get(original.casefold(), '')


def parse_server_result(data, requested_language='auto'):
    if not isinstance(data, dict):
        raise RuntimeError('Unexpected response from the local speech engine')
    original = str(data.get('text') or '').strip()
    source = (normalize_speech_language(requested_language)
              if requested_language != 'auto'
              else whisper_language_code(data.get('language', '')))
    if not source or source == 'auto':
        raise RuntimeError('Whisper could not identify the spoken language')
    if not original:
        raise RuntimeError('Whisper did not detect speech. Try a longer recording.')
    return original, source


def encode_multipart(wav, fields):
    boundary = 'EchoBridge' + uuid.uuid4().hex
    chunks = []
    def field(name, content, filename=None, content_type=None):
        chunks.append(('--' + boundary + '\r\n').encode('ascii'))
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        chunks.append((disposition + '\r\n').encode('ascii'))
        if content_type:
            chunks.append((f'Content-Type: {content_type}\r\n').encode('ascii'))
        chunks.append(b'\r\n')
        chunks.append(content if isinstance(content, bytes) else str(content).encode('utf-8'))
        chunks.append(b'\r\n')
    field('file', Path(wav).read_bytes(), filename='speech.wav', content_type='audio/wav')
    for key, value in fields.items():
        field(key, value)
    chunks.append(('--' + boundary + '--\r\n').encode('ascii'))
    return b''.join(chunks), 'multipart/form-data; boundary=' + boundary


def wait_for_ready(port, path, timeout=90, process_alive=None):
    deadline = time.monotonic() + timeout
    url = f'http://127.0.0.1:{int(port)}{path}/'
    while time.monotonic() < deadline:
        if process_alive is not None and not process_alive():
            raise RuntimeError('Whisper preload process stopped before model finished loading')
        try:
            with urllib.request.urlopen(url, timeout=0.5) as res:
                if res.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    raise TimeoutError('Whisper did not finish loading within 90 seconds')


def windows_process_alive(pid):
    """Check whether the child model server is still loading without blocking."""
    if not pid:
        return True
    import os
    if os.name != 'nt':
        return True
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x00100000, False, int(pid))
    if not handle:
        return False
    try:
        # WAIT_TIMEOUT means the process is still running.
        return kernel.WaitForSingleObject(handle, 0) == 0x00000102
    finally:
        kernel.CloseHandle(handle)


def transcribe_preloaded(wav, language, port, request_path, process_id=None):
    wait_for_ready(port, request_path, process_alive=(lambda: windows_process_alive(process_id)))
    values = {
        'language': language,
        'response_format': 'verbose_json',
        'no_language_probabilities': 'true',
        'no_context': 'true',
        'suppress_nst': 'true',
        'no_timestamps': 'true',
    }
    body, media_type = encode_multipart(wav, values)
    url = f'http://127.0.0.1:{int(port)}{request_path}/inference'
    request = urllib.request.Request(url, data=body, headers={'Content-Type': media_type}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=600) as res:
            response = json.loads(res.read().decode('utf-8-sig'))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Local Whisper server returned HTTP {exc.code}') from exc
    return parse_server_result(response, language)
