"""Short-lived whisper-server preloading for Windows push-to-talk.

The server is launched *after* the microphone opens and is killed once the
recording's inference worker finishes. Nothing runs when EchoBridge is idle.
If a legacy runtime contains only whisper-cli, the worker safely falls back
to loading the model after recording, and the UI explains that limitation.
"""
from __future__ import annotations

import secrets
import socket
from dataclasses import dataclass
from pathlib import Path


def find_server(cli_path):
    """Only accept the server bundled alongside the selected whisper-cli."""
    if not cli_path:
        return None
    cli = Path(cli_path)
    same_directory = cli.with_name('whisper-server.exe')
    return same_directory if same_directory.is_file() else None


def unused_loopback_port():
    """Get a high ephemeral localhost port (server binds after socket closes)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


@dataclass(frozen=True)
class PreloadSpec:
    program: str
    args: tuple[str, ...]
    port: int
    request_path: str


def make_preload_spec(server_path, model_path, device, gpu_index=0, port=None, token=None, source='auto'):
    """Build a localhost-only, isolated server command from installed files."""
    if device not in ('cpu', 'amd', 'nvidia'):
        raise ValueError('Invalid transcription device')
    if port is None:
        port = unused_loopback_port()
    if not 1024 <= int(port) <= 65535:
        raise ValueError('Invalid listening port')
    token = token or secrets.token_hex(16)
    if not token.isalnum():
        raise ValueError('Invalid local server identifier')
    path = '/echo-' + token
    args = [
        '-m', str(model_path), '--host', '127.0.0.1',
        '--port', str(port), '--request-path', path,
        '-l', str(source), '-nt', '-nf', '-sns',
    ]
    if device == 'cpu':
        args.append('-ng')
    else:
        args.extend(['-dev', str(int(gpu_index))])
    return PreloadSpec(str(server_path), tuple(args), int(port), path)
