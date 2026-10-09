"""Windows 全域快捷鍵（RegisterHotKey），喺自己嘅 thread 跑訊息迴圈。"""

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
WM_HOTKEY = 0x0312


def register(modifiers: int, vk: int, callback: Callable[[], None]) -> threading.Thread:
    """回傳嘅 thread 有 ok 屬性；False 代表註冊失敗（例如組合鍵已被其他程式佔用）。"""
    ready = threading.Event()
    result: dict = {}

    def loop():
        user32 = ctypes.windll.user32
        ok = user32.RegisterHotKey(None, 1, modifiers | MOD_NOREPEAT, vk)
        result["ok"] = bool(ok)
        ready.set()
        if not ok:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                callback()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    ready.wait(2)
    thread.ok = result.get("ok", False)  # type: ignore[attr-defined]
    return thread
