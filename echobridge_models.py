"""EchoBridge model and whisper.cpp runtime paths. No inference models loaded here."""
import os
from pathlib import Path
from PySide6.QtCore import QSettings

SETTINGS = QSettings('EchoBridge', 'EchoBridge')
ROOT = Path(os.environ.get('ECHOBRIDGE_DATA_DIR') or (Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'EchoBridge'))
MODELS = ROOT / 'models'
RUNTIMES = ROOT / 'runtimes'
VAD_PATH = MODELS / 'ggml-silero-v6.2.0.bin'

def vad_ready():
    return VAD_PATH.is_file() and 700_000 <= VAD_PATH.stat().st_size <= 2_000_000


MODEL_FILES = {
    'tiny': ('ggml-tiny.bin', '~75 MB'),
    'base': ('ggml-base.bin', '~142 MB'),
    'small': ('ggml-small.bin', '~466 MB'),
    'medium': ('ggml-medium.bin', '~1.5 GB'),
    'large-v3-turbo-q5_0': ('ggml-large-v3-turbo-q5_0.bin', '~550 MB'),
    'large-v3': ('ggml-large-v3.bin', '~3.1 GB'),
}
# Lower bounds guard against partially downloaded or HTML error files.
MIN_BYTES = {'tiny': 60_000_000, 'base': 110_000_000, 'small': 390_000_000,
             'medium': 1_250_000_000, 'large-v3-turbo-q5_0': 420_000_000,
             'large-v3': 2_650_000_000}
DEVICES = {'cpu': 'CPU', 'amd': 'AMD GPU (Vulkan)', 'nvidia': 'NVIDIA GPU (Vulkan)'}


def model_name():
    value = str(SETTINGS.value('whisper_model', 'small'))
    return value if value in MODEL_FILES else 'small'


def device_name():
    value = str(SETTINGS.value('whisper_device', 'cpu'))
    return value if value in DEVICES else 'cpu'


def model_path(name=None):
    name = name or model_name()
    return MODELS / MODEL_FILES[name][0]


def model_ready(name=None):
    name = name or model_name()
    path = model_path(name)
    return path.is_file() and path.stat().st_size >= MIN_BYTES[name]


def runtime_path(device=None):
    device = device or device_name()
    root = RUNTIMES / ('cpu' if device == 'cpu' else 'vulkan')
    if root.exists():
        items = sorted(root.rglob('whisper-cli.exe'))
        if items:
            return next((cli for cli in items if cli.with_name('whisper-server.exe').is_file()), items[0])
    return None


def ready_error():
    if not model_ready():
        return f'Model {model_name()} is not installed or incomplete. Open Settings > AI Models to download it.'
    if runtime_path() is None:
        backend = 'CPU' if device_name() == 'cpu' else 'Vulkan GPU'
        return f'{backend} runtime not installed. Open Settings > AI Models to install it.'
    return None
