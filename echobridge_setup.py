"""On-demand, short-lived installer invoked from EchoBridge Settings.

CPU: official ggml-org release b5454 (x64). GPU: windows Vulkan asset from
jiang1997/whisper.cpp-release; the GitHub API must confirm the asset exists.
All downloads are explicit and never run during a recording.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from echobridge_models import MODEL_FILES, MIN_BYTES, MODELS, RUNTIMES, VAD_PATH, vad_ready, model_path, model_ready
from echobridge_translation_routes import plan_translation

CPU_URL = 'https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip'
CPU_SHA256 = '6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb'
VULKAN_API = 'https://api.github.com/repos/jiang1997/whisper.cpp-release/releases/latest'
VULKAN_RELEASES = 'https://github.com/jiang1997/whisper.cpp-release/releases'
MODEL_SOURCE = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/'
VAD_SOURCE = 'https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin'


def emit(event, **values):
    print(json.dumps({'event': event, **values}, ensure_ascii=True), flush=True)


def request(url):
    return urllib.request.Request(url, headers={
        'User-Agent': 'EchoBridge/0.2 (Windows desktop application)',
        'Accept': 'application/vnd.github+json' if 'api.github.com' in url else '*/*',
        'X-GitHub-Api-Version': '2022-11-28' if 'api.github.com' in url else '2022-11-28',
    })


def fetch_json(url):
    try:
        with urllib.request.urlopen(request(url), timeout=40) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        if err.code == 403:
            raise RuntimeError('GitHub API rate limited this download. Try again later or use the release page: ' + VULKAN_RELEASES) from err
        raise RuntimeError(f'Cannot check GitHub releases (HTTP {err.code}). Release page: {VULKAN_RELEASES}') from err


def choose_vulkan_asset(release):
    """Must be a Windows x64 archive containing whisper-cli, not server-only."""
    assets = release.get('assets') or []
    possibilities = []
    for asset in assets:
        name = str(asset.get('name', '')).lower()
        url = str(asset.get('browser_download_url', ''))
        if not (name.endswith('.zip') or name.endswith('.tar.gz')):
            continue
        if not ('windows' in name or 'win-' in name or 'win_' in name):
            continue
        if not ('x64' in name or 'x86_64' in name or 'amd64' in name):
            continue
        if url.startswith('https://github.com/jiang1997/whisper.cpp-release/releases/download/'):
            possibilities.append(asset)
    # The repository is Windows Vulkan by release contract; inspect archive for whisper-cli before installing.
    if not possibilities:
        raise RuntimeError('No Windows x64 Vulkan archive was published in this release. Open: ' + VULKAN_RELEASES)
    possibilities.sort(key=lambda a: (0 if 'vulkan' in a['name'].lower() else 1, a['name']))
    return possibilities[0]


def download(url, destination, label, min_size=1_000_000, expected_size=None, sha256=None):
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + '.part')
    emit('phase', message=label)
    try:
        try:
            response = urllib.request.urlopen(request(url), timeout=60)
        except urllib.error.HTTPError as err:
            raise RuntimeError(f'Download failed (HTTP {err.code}) for {label}.') from err
        with response, part.open('wb') as output:
            total = int(response.headers.get('Content-Length') or 0)
            hasher = hashlib.sha256()
            amount = 0
            last = -1
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                hasher.update(chunk)
                amount += len(chunk)
                if total:
                    percentage = min(100, int(amount * 100 / total))
                    if percentage >= last + 2 or percentage == 100:
                        emit('progress', percent=percentage)
                        last = percentage
                elif amount // (15 * 1024 * 1024) > (amount - len(chunk)) // (15 * 1024 * 1024):
                    emit('phase', message=f'{label}: {amount / 1048576:.0f} MB received')
            if amount < min_size:
                raise RuntimeError('Downloaded file is too small: transfer incomplete or incorrect download.')
            if total and amount != total:
                raise RuntimeError('Incomplete download (received bytes do not match Content-Length).')
            if expected_size and amount != expected_size:
                raise RuntimeError('Downloaded archive size does not match GitHub release metadata.')
            if sha256 and hasher.hexdigest().lower() != sha256.lower():
                raise RuntimeError('SHA256 mismatch — installation stopped for safety.')
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)


def install_model(name):
    if name not in MODEL_FILES:
        raise ValueError('Unknown model')
    if model_ready(name):
        emit('done', message=f'{name} already installed.')
        return
    # Always redownload an incomplete/corrupt existing file; never trust only its existence.
    url = MODEL_SOURCE + MODEL_FILES[name][0]
    download(url, model_path(name), f'Downloading {name} model', min_size=MIN_BYTES[name])
    if not model_ready(name):
        raise RuntimeError(f'Model {name} failed validation.')
    emit('done', message=f'Model {name} installed and verified by size.')


def install_vad():
    """Download an optional 0.9 MB speech detector; never during recording."""
    if vad_ready():
        emit('done', message='Silero speech detector is already installed.')
        return
    download(VAD_SOURCE, VAD_PATH, 'Downloading Silero speech detector', min_size=700_000)
    if not vad_ready():
        raise RuntimeError('Silero speech detector download is incomplete.')
    emit('done', message='Silero speech detector installed. It will filter silence during transcription.')


def safe_extract(archive, destination):
    archive = Path(archive)
    dest = Path(destination).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    total_limit = 2 * 1024 * 1024 * 1024
    max_files = 25000
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            if len(members) > max_files or sum(x.file_size for x in members) > total_limit:
                raise RuntimeError('Unexpectedly large archive')
            for info in members:
                target = (dest / info.filename).resolve()
                if not target.is_relative_to(dest) or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise RuntimeError('Unsafe ZIP entry')
            z.extractall(dest)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive, 'r:*') as t:
            members = t.getmembers()
            if len(members) > max_files or sum(x.size for x in members) > total_limit:
                raise RuntimeError('Unexpectedly large archive')
            for item in members:
                target = (dest / item.name).resolve()
                if not target.is_relative_to(dest) or not (item.isfile() or item.isdir()):
                    raise RuntimeError('Unsafe TAR entry')
            for item in members:
                target = dest / item.name
                if item.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    stream = t.extractfile(item)
                    if stream is None:
                        raise RuntimeError('Invalid TAR payload')
                    with stream, target.open('wb') as output:
                        shutil.copyfileobj(stream, output)
    else:
        raise RuntimeError('Downloaded release is not a supported ZIP or TAR archive.')


def install_runtime(backend):
    if backend not in ('cpu', 'gpu'):
        raise ValueError('Invalid runtime choice')
    if backend == 'cpu':
        url = CPU_URL
        name = 'whisper-bin-x64.zip'
        expected_size = None
        known_hash = CPU_SHA256
    else:
        emit('phase', message='Checking published Vulkan files on GitHub')
        asset = choose_vulkan_asset(fetch_json(VULKAN_API))
        url = asset['browser_download_url']
        name = asset['name']
        expected_size = int(asset.get('size') or 0) or None
        digest = str(asset.get('digest') or '')
        known_hash = digest[7:] if digest.startswith('sha256:') else None
    root = RUNTIMES / ('cpu' if backend == 'cpu' else 'vulkan')
    with tempfile.TemporaryDirectory(prefix='echobridge_install_') as temp:
        temp = Path(temp)
        archive = temp / name
        download(url, archive, f'Downloading {backend.upper()} runtime',
                 min_size=1_000_000, expected_size=expected_size, sha256=known_hash)
        emit('phase', message='Checking and extracting runtime')
        staged = temp / 'unpacked'
        safe_extract(archive, staged)
        cli_list = list(staged.rglob('whisper-cli.exe'))
        if not cli_list:
            raise RuntimeError('The downloaded archive has no whisper-cli.exe. No runtime installed. Release: ' + (VULKAN_RELEASES if backend == 'gpu' else CPU_URL))
        if not any(cli.stat().st_size > 100000 for cli in cli_list):
            raise RuntimeError('whisper-cli.exe in the archive is invalid.')
        if not any(cli.with_name('whisper-server.exe').is_file() for cli in cli_list):
            raise RuntimeError('This runtime does not include whisper-server.exe for model preloading. No changes installed.')
        # Keep nearby DLL dependencies in their original positions.
        root.parent.mkdir(parents=True, exist_ok=True)
        old = root.with_name(root.name + '_previous')
        if old.exists():
            shutil.rmtree(old)
        if root.exists():
            root.rename(old)
        try:
            shutil.move(str(staged), str(root))
        except Exception:
            if old.exists() and not root.exists():
                old.rename(root)
            raise
        if old.exists():
            shutil.rmtree(old)
    emit('done', message=f'{backend.upper()} runtime installed successfully.')


def install_pair(source, target):
    import argostranslate.package as pkg
    if source == target:
        emit('done', message=f'{source} → {target}: No translation needed.')
        return
    installed = {(p.from_code, p.to_code) for p in pkg.get_installed_packages()}
    if (source, target) in installed or ((source, 'en') in installed and ('en', target) in installed):
        emit('done', message=f'{source} → {target} already installed.')
        return
    emit('phase', message=f'Checking offline packages for {source} → {target}')
    pkg.update_package_index()
    available = {(p.from_code, p.to_code): p for p in pkg.get_available_packages()}
    route = plan_translation(source, target, installed, available)
    for a, b in route:
        if (a, b) in installed:
            continue
        emit('phase', message=f'Installing {a} → {b} (requested: {source} → {target})')
        pkg.install_from_path(available[(a, b)].download())
        installed = {(p.from_code, p.to_code) for p in pkg.get_installed_packages()}
        if (a, b) not in installed:
            raise RuntimeError(f'Package installed but not registered: {a} → {b}')
    if not ((source, target) in installed or ((source, 'en') in installed and ('en', target) in installed)):
        raise RuntimeError(f'Required offline route {source} → {target} was not installed.')
    emit('done', message=f'Offline translation {source} → {target} installed. No language settings were changed.')



def remove_model(name):
    if name not in MODEL_FILES:
        raise ValueError('Unknown Whisper model')
    dest = model_path(name)
    if not dest.is_file():
        emit('done', message=f'{name} is already removed.')
        return
    dest.unlink()
    emit('done', message=f'Whisper {name} removed from disk.')


def remove_runtime(backend):
    if backend not in ('cpu', 'gpu'):
        raise ValueError('Unknown runtime')
    root = RUNTIMES / ('cpu' if backend == 'cpu' else 'vulkan')
    if root.is_dir():
        shutil.rmtree(root)
    emit('done', message=f'{backend.upper()} runtime removed.')


def remove_vad():
    if VAD_PATH.is_file():
        VAD_PATH.unlink()
    emit('done', message='Speech detector removed.')


def remove_pair(source, target):
    import argostranslate.package as pkg
    if not source or not target or source == target:
        raise ValueError('Select one installed language pair')
    matching = [p for p in pkg.get_installed_packages()
                if p.from_code == source and p.to_code == target and p.type == 'translate']
    if len(matching) != 1:
        raise RuntimeError('The selected translation package was not found or was ambiguous.')
    pkg.uninstall(matching[0])
    emit('done', message=f'Translation package {source} → {target} removed.')


def install_bundle(device, name, source, target):
    from echobridge_models import device_name, model_ready, model_path, runtime_path, vad_ready
    from echobridge_preload import find_server
    if device not in ('cpu', 'amd', 'nvidia') or name not in MODEL_FILES:
        raise ValueError('Unsupported processing configuration')
    # The settings process reads the selected GPU independently of this command;
    # we only install the appropriate runtime and model here.
    if not source or source == 'auto' or not target:
        raise ValueError('Choose the main spoken language and target language before downloading')
    backend = 'cpu' if device == 'cpu' else 'gpu'
    steps = [
        ('Whisper runtime', lambda: install_runtime(backend),
         lambda: find_server(runtime_path(device)) is not None),
        ('Speech model', lambda: install_model(name), lambda: model_ready(name)),
        ('Speech detector', install_vad, vad_ready),
        (f'Offline translation {source} → {target}',
         lambda: install_pair(source, target),
         lambda: _pair_ready(source, target)),
    ]
    for i, (label, install, ready) in enumerate(steps, 1):
        emit('component', message=f'Step {i}/{len(steps)} — {label}', step=i, total=len(steps))
        if ready():
            emit('phase', message=f'{label} already installed — skipping download')
        else:
            install()
        if not ready():
            raise RuntimeError(f'{label} could not be verified after installation')
    emit('done', message='All four components installed and verified. Ready to record.')


def _pair_ready(source, target):
    if source == target:
        return True
    import argostranslate.package as pkg
    available = {(p.from_code, p.to_code) for p in pkg.get_installed_packages()
                 if p.type == 'translate'}
    try:
        plan_translation(source, target, available)
        return True
    except (RuntimeError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--model', choices=MODEL_FILES)
    action.add_argument('--vad', action='store_true')
    action.add_argument('--runtime', choices=['cpu', 'gpu'])
    action.add_argument('--pair', nargs=2, metavar=('SOURCE', 'TARGET'))
    action.add_argument('--bundle', nargs=4, metavar=('DEVICE', 'MODEL', 'SOURCE', 'TARGET'))
    action.add_argument('--remove-model', choices=MODEL_FILES)
    action.add_argument('--remove-runtime', choices=['cpu', 'gpu'])
    action.add_argument('--remove-vad', action='store_true')
    action.add_argument('--remove-pair', nargs=2, metavar=('SOURCE', 'TARGET'))
    args = parser.parse_args()
    try:
        if args.bundle:
            install_bundle(*args.bundle)
        elif args.vad:
            install_vad()
        elif args.model:
            install_model(args.model)
        elif args.runtime:
            install_runtime(args.runtime)
        elif args.pair:
            install_pair(*args.pair)
        elif args.remove_model:
            remove_model(args.remove_model)
        elif args.remove_runtime:
            remove_runtime(args.remove_runtime)
        elif args.remove_vad:
            remove_vad()
        elif args.remove_pair:
            remove_pair(*args.remove_pair)
        return 0
    except Exception as exc:
        emit('error', message=f'{type(exc).__name__}: {exc}')
        return 1

if __name__ == '__main__':
    sys.exit(main())
