"""PyInstaller runtime hook: restore QProcess pipes in a Windows GUI executable.

EchoBridge runs `EchoBridge.exe --worker` and `EchoBridge.exe --setup` from
QProcess. With --windowed, Python normally gets sys.std* = None. The Qt
parent provides actual Windows standard handles, which we bind to Python.
"""
import os
import sys


def restore(name, handle_id, mode, flags):
    if getattr(sys, name, None) is not None:
        return
    import ctypes
    import msvcrt

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = (ctypes.c_uint32,)
    kernel.GetStdHandle.restype = ctypes.c_void_p
    raw = kernel.GetStdHandle(handle_id & 0xFFFFFFFF)
    if raw is None or raw == ctypes.c_void_p(-1).value:
        if name == 'stdin':
            # A GUI child can legitimately have no stdin (for example, the
            # --help smoke test or the model installer). Only the worker
            # needs input, and it will report invalid/missing input itself.
            stream = open(os.devnull, 'r', encoding='utf-8')
            setattr(sys, name, stream)
            setattr(sys, '__' + name + '__', stream)
            return
        raise RuntimeError('Missing redirected Windows standard handle for ' + name)

    # QProcess creates pipes for all three standard streams. The child owns
    # these handles and exits after performing its task.
    fd = msvcrt.open_osfhandle(int(raw), flags | os.O_BINARY)
    stream = os.fdopen(fd, mode, encoding='utf-8', errors='replace', buffering=1)
    setattr(sys, name, stream)
    setattr(sys, '__' + name + '__', stream)


if os.name == 'nt':
    if '--worker' in sys.argv or '--setup' in sys.argv:
        restore('stdin', -10, 'r', os.O_RDONLY)
        restore('stdout', -11, 'w', os.O_WRONLY)
        restore('stderr', -12, 'w', os.O_WRONLY)
    else:
        # The UI does not need a console, but should retain diagnostics.
        from pathlib import Path
        root = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'EchoBridge' / 'logs'
        root.mkdir(parents=True, exist_ok=True)
        out = (root / 'application.log').open('a', encoding='utf-8', buffering=1)
        sys.stdout = out
        sys.stderr = out
        sys.__stdout__ = out
        sys.__stderr__ = out
        if sys.stdin is None:
            sys.stdin = open(os.devnull, 'r')
