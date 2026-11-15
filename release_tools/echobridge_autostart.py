"""Windows per-user launch-at-login switch for the installed EchoBridge executable.

Never requires administrator privileges. No audio capture occurs until a hotkey press.
"""
from __future__ import annotations

import os
import sys

RUN_SUBKEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'EchoBridge'


def installed_executable():
    """Only a packaged .exe is stable enough to register at login."""
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        return None
    path = os.path.abspath(sys.executable)
    if not path.lower().endswith('\\echobridge.exe'):
        return None
    return path


def startup_command(path):
    if not path or '\"' in path:
        raise ValueError('Invalid executable path')
    return f'"{os.path.abspath(path)}"'


def enabled():
    path = installed_executable()
    if path is None:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_SUBKEY, 0, winreg.KEY_READ) as key:
            value, kind = winreg.QueryValueEx(key, VALUE_NAME)
            return kind == winreg.REG_SZ and str(value).casefold() == startup_command(path).casefold()
    except FileNotFoundError:
        return False


def set_enabled(enable):
    path = installed_executable()
    if path is None:
        raise RuntimeError('Start with Windows can be changed after installing EchoBridge.exe.')
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_SUBKEY, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        if enable:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command(path))
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
