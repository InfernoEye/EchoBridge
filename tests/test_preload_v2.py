from pathlib import Path

import pytest

from echobridge_preload import find_server, make_preload_spec
from echobridge_server_client import encode_multipart, parse_server_result, whisper_language_code


def test_short_lived_server_launch_cpu_has_localhost_and_no_gpu():
    spec = make_preload_spec('whisper-server.exe', 'model.bin', 'cpu', port=55555, token='abc123', source='pl')
    assert spec.request_path == '/echo-abc123'
    assert spec.args[spec.args.index('--host') + 1] == '127.0.0.1'
    assert spec.args[spec.args.index('--port') + 1] == '55555'
    assert '-ng' in spec.args
    assert '-dev' not in spec.args


def test_short_lived_server_launch_gpu():
    spec = make_preload_spec('server.exe', 'model.bin', 'amd', gpu_index=3, port=44444, token='abc123')
    assert spec.args[-2:] == ('-dev', '3')
    assert '-ng' not in spec.args


def test_invalid_server_parameters_rejected():
    with pytest.raises(ValueError):
        make_preload_spec('server', 'model', 'cpu', port=20)
    with pytest.raises(ValueError):
        make_preload_spec('server', 'model', 'nonsense')


def test_find_server_only_same_directory(tmp_path):
    cli = tmp_path / 'whisper-cli.exe'
    cli.write_bytes(b'x')
    assert find_server(cli) is None
    (tmp_path / 'whisper-server.exe').write_bytes(b'x')
    assert find_server(cli) == tmp_path / 'whisper-server.exe'


def test_verbose_json_friendly_language_names():
    assert whisper_language_code('Polish') == 'pl'
    assert whisper_language_code('German') == 'de'
    assert whisper_language_code('pl') == 'pl'
    assert parse_server_result({'text': 'Jak się dzisiaj czujesz?', 'language': 'Polish'}, 'auto') == (
        'Jak się dzisiaj czujesz?', 'pl'
    )


def test_manual_language_overrides_auto_detection():
    assert parse_server_result({'text': 'Cześć', 'language': 'English'}, 'pl') == ('Cześć', 'pl')


def test_missing_server_result_rejected():
    with pytest.raises(RuntimeError, match='did not detect speech'):
        parse_server_result({'text': ' ', 'language': 'Polish'})


def test_multipart_wav_file_and_language(tmp_path):
    wav = tmp_path / 'a.wav'
    wav.write_bytes(b'RIFF' + b'\x00' * 44)
    body, content_type = encode_multipart(wav, {'language': 'pl'})
    assert b'RIFF' in body
    assert b'name="language"' in body
    assert b'pl\r\n' in body
    assert 'multipart/form-data; boundary=' in content_type
