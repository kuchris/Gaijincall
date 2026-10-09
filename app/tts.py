"""主程式一方嘅 TTS client：啟動 OmniVoice worker，逐句合成。"""

import json
import struct
import subprocess
import threading

import numpy as np

from paths import OMNIVOICE_PYTHON, ROOT

LOG_DIR = ROOT / "logs"

# 對話語言代碼 → OmniVoice 語言代碼
TTS_LANGS = {"yue": "yue", "cmn": "zh", "ja": "ja", "en": "en"}


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
            raise RuntimeError(f"TTS worker 啟動失敗，詳情睇 {LOG_DIR / 'tts_worker.log'}")

    def synth(self, text: str, lang: str) -> np.ndarray:
        """回傳 48 kHz mono float32；冇可讀字（例如只得標點）就回傳空陣列。"""
        if not any(ch.isalnum() for ch in text):
            return np.zeros(0, dtype=np.float32)
        with self._lock:
            self._proc.stdin.write((json.dumps({"text": text, "lang": TTS_LANGS[lang]}) + "\n").encode())
            self._proc.stdin.flush()
            (n,) = struct.unpack("<I", self._read(4))
            return np.frombuffer(self._read(n * 4), dtype="<f4").copy()

    def _read(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._proc.stdout.read(n - len(data))
            if not chunk:
                raise RuntimeError(f"TTS worker 已結束，詳情睇 {LOG_DIR / 'tts_worker.log'}")
            data += chunk
        return data

    def close(self):
        self._proc.kill()
