"""Low-latency Windows push-to-talk hotkey with key-up events."""
import ctypes
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal


VK = {
    "Space": 0x20, "Tab": 0x09, "Backspace": 0x08, "Esc": 0x1B,
    "Escape": 0x1B, "Insert": 0x2D, "Delete": 0x2E, "Home": 0x24,
    "End": 0x23, "PgUp": 0x21, "PageUp": 0x21, "PgDown": 0x22,
    "PageDown": 0x22, "Left": 0x25, "Up": 0x26, "Right": 0x27,
    "Down": 0x28, "Return": 0x0D, "Enter": 0x0D,
}


def parse_hotkey(text):
    parts = [p.strip() for p in str(text).split("+") if p.strip()]
    if not parts:
        raise ValueError("Choose a keyboard shortcut.")
    modifiers = set()
    for part in parts[:-1]:
        mod = {"Ctrl": "ctrl", "Control": "ctrl", "Alt": "alt",
               "Shift": "shift", "Meta": "win", "Win": "win"}.get(part)
        if mod is None:
            raise ValueError(f"Unsupported modifier: {part}")
        modifiers.add(mod)
    key = parts[-1]
    if len(key) == 1 and key.upper() in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        vk = ord(key.upper())
    elif key.upper().startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        vk = VK.get(key)
    if vk is None:
        raise ValueError(f"Unsupported shortcut key: {key}. Try F8 or Ctrl+Shift+F8.")
    return vk, modifiers


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class WindowsHotkey(QObject):
    pressed = Signal()
    released = Signal()
    error = Signal(str)

    def __init__(self, shortcut="F8", parent=None):
        super().__init__(parent)
        self._vk, self._mods = parse_hotkey(shortcut)
        self._suspended = False
        self._active = False
        self.last_pressed_ns = 0
        self._thread_id = None
        self._hook = None
        self._thread = None
        self._stop = threading.Event()

    def set_hotkey(self, shortcut):
        vk, mods = parse_hotkey(shortcut)
        if self._active:
            self._active = False
            self.released.emit()
        self._vk, self._mods = vk, mods

    def set_suspended(self, suspended):
        if suspended and self._active:
            self._active = False
            self.released.emit()
        self._suspended = bool(suspended)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="EchoBridgeHotkey")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread:
            self._thread.join(timeout=1.0)

    def _run(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                       wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                         wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), ctypes.c_void_p,
                                       wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = ctypes.c_int
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                              wintypes.WPARAM, wintypes.LPARAM]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        def mod_pressed(vk):
            return bool(user32.GetAsyncKeyState(vk) & 0x8000)

        def modifiers_match(mods):
            present = {"ctrl": mod_pressed(0x11), "alt": mod_pressed(0x12),
                       "shift": mod_pressed(0x10), "win": mod_pressed(0x5B) or mod_pressed(0x5C)}
            return all(present[name] == (name in mods) for name in present)

        def callback(code, wparam, lparam):
            if code == 0 and not self._suspended and not self._stop.is_set():
                kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk = kb.vkCode
                event = int(wparam)
                if vk == self._vk:
                    if event in (0x0100, 0x0104) and not self._active and modifiers_match(self._mods):
                        self._active = True
                        self.last_pressed_ns = time.perf_counter_ns()
                        self.pressed.emit()
                        return 1
                    if event in (0x0101, 0x0105) and self._active:
                        self._active = False
                        self.released.emit()
                        return 1
                    if self._active:
                        return 1
            return user32.CallNextHookEx(self._hook, code, wparam, lparam)

        self._callback = HOOKPROC(callback)
        self._thread_id = kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(13, self._callback, kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            self.error.emit(f"Keyboard hook failed (Windows error {ctypes.get_last_error()})")
            self._thread_id = None
            return
        try:
            message = wintypes.MSG()
            while not self._stop.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._thread_id = None
            self._active = False
