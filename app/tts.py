"""主程式一方嘅 TTS client：啟動 OmniVoice worker，逐句合成。"""

import json
import re
import struct
import subprocess
import threading

import numpy as np

from paths import OMNIVOICE_PYTHON, ROOT

LOG_DIR = ROOT / "logs"

# 對話語言代碼 → OmniVoice 語言代碼
TTS_LANGS = {"yue": "yue", "cmn": "zh", "ja": "ja", "en": "en"}
KANA = re.compile(r"[぀-ヿ]")
CJK = re.compile(r"[぀-ヿ㐀-鿿]")
LATIN = re.compile(r"[A-Za-z]")


def tts_lang(text: str, lang: str) -> str:
    """按句子實際文字揀 OmniVoice 語言，避免例如用日文讀中文句（實測會讀錯）。"""
    if KANA.search(text):
        return "ja"
    if not CJK.search(text) and LATIN.search(text):
        return "en"
    if lang in ("en", "ja") and CJK.search(text):
        # 冇假名嘅漢字句：日文鎖定時可能係純漢字日文（例如「了解」），保留日文；英文鎖定時當中文
        return "ja" if lang == "ja" else "zh"
    return TTS_LANGS[lang]


class TTS:
    def __init__(self):
        LOG_DIR.mkdir(exist_ok=True)
        self._log = open(LOG_DIR / "tts_worker.log", "ab")
        self._proc = subprocess.Popen(
            [str(OMNIVOICE_PYTHON), str(ROOT / "app" / "tts_worker.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
        )
        self._lock = threading.Lock()
        if self._proc.stdout.readline().strip() != b"READY":
            raise RuntimeError(f"TTS worker failed to start; see {LOG_DIR / 'tts_worker.log'}")

    def synth(self, text: str, lang: str, instruct: str | None = None, speed: float = 1.0) -> np.ndarray:
        """回傳 48 kHz mono float32；冇可讀字（例如只得標點）就回傳空陣列。
        instruct：OmniVoice voice design（例如 "female, young adult, low pitch"），None 用 worker 預設。"""
        if not any(ch.isalnum() for ch in text):
            return np.zeros(0, dtype=np.float32)
        req = {"text": text, "lang": tts_lang(text, lang), "instruct": instruct, "speed": speed}
        with self._lock:
            self._proc.stdin.write((json.dumps(req) + "\n").encode())
            self._proc.stdin.flush()
            (n,) = struct.unpack("<I", self._read(4))
            return np.frombuffer(self._read(n * 4), dtype="<f4").copy()

    def _read(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._proc.stdout.read(n - len(data))
            if not chunk:
                raise RuntimeError(f"TTS worker exited; see {LOG_DIR / 'tts_worker.log'}")
            data += chunk
        return data

    def close(self):
        self._proc.kill()
