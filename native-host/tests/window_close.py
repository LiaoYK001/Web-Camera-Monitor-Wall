#!/usr/bin/env python3
"""Close a product window the way a user does, so the product shuts down itself.

The product launcher (desktop/native/job_host.cpp) owns a Job with
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: terminating the launcher process closes that
Job and the operating system kills the supervisor and every service with it. The
supervisor's shutdown path then never runs, so ``run/native-status.json`` keeps
reporting ``phase: "running"`` and no normal-stop evidence exists.

Posting WM_CLOSE to the frontend window is what the supervisor itself does when a
stop is requested (``product_supervisor.close_frontend``) and what a user does, so
the gate can require the real ordered shutdown instead of a hard kill.
"""
from __future__ import annotations

import ctypes
import re
from ctypes import wintypes

CLOSE_MESSAGE = 0x0010  # WM_CLOSE
GW_STYLE = -16
GW_OWNER = 4
CAPTION_BITS = 0x00C00000
QT_WINDOW_CLASS = re.compile(r"Qt[0-9]+QWindowIcon")


def close_closable_windows(pids) -> int:
    """Post WM_CLOSE to every visible top-level Qt window owned by ``pids``.

    Qt creates clipboard, theme and tool windows before the real product window;
    those are not closable frontends, so only a captioned, unowned Qt top level
    receives the message. Returns how many windows were closed.
    """
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.PostMessageW.restype = wintypes.BOOL
    user.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    user.EnumWindows.restype = wintypes.BOOL
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.restype = ctypes.c_int
    user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindow.restype = wintypes.HWND
    owners = {int(pid) for pid in pids}
    posted = 0

    def close(window, _):
        nonlocal posted
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value not in owners:
            return True
        name = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(window, name, len(name))
        if QT_WINDOW_CLASS.fullmatch(name.value) and \
                user.GetWindowLongPtrW(window, GW_STYLE) & CAPTION_BITS and \
                not user.GetWindow(window, GW_OWNER):
            if user.PostMessageW(window, CLOSE_MESSAGE, 0, 0):
                posted += 1
        return True

    if not user.EnumWindows(callback(close), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return posted
