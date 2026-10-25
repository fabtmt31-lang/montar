# SPDX-License-Identifier: GPL-3.0-or-later
"""Processus : savoir si un autre processus existe encore (Linux et Windows)."""
from __future__ import annotations

import os
import sys


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _alive_windows(pid)
    try:
        os.kill(pid, 0)  # signal 0 : simple vérification
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _alive_windows(pid: int) -> bool:
    # surtout pas os.kill(pid, 0) : sous Windows, il termine le processus
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    query_limited_information, still_active, access_denied = 0x1000, 259, 5
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == access_denied
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
