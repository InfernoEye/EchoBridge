"""Best-effort Windows CPU scheduling for Whisper preloading.

Recording is already open before this runs. Lowering the inference process
priority protects audio capture from contention on modest CPUs.
"""
import ctypes
import sys
from ctypes import wintypes


def lower_whisper_priority(pid):
    if sys.platform != 'win32' or not pid:
        return False
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        PROCESS_SET_INFORMATION = 0x0200
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        handle = kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            return bool(kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS))
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, ValueError, OverflowError):
        return False
