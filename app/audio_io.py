"""Discord 收音（ProcLoopback）同虛擬咪播音。"""

import collections
import ctypes
import subprocess
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd
import soxr

from paths import PROC_LOOPBACK

CAPTURE_RATE = 48000
VAD_RATE = 16000
PLAY_RATE = 48000


def find_wasapi_device(name_part: str, kind: str) -> int:
    """按名稱片段搵 WASAPI 裝置；kind 係 'input' 或 'output'。"""
    hostapis = sd.query_hostapis()
    candidates = [
        (i, d["name"]) for i, d in enumerate(sd.query_devices())
        if "WASAPI" in hostapis[d["hostapi"]]["name"] and d[f"max_{kind}_channels"] > 0
    ]
    exact = [i for i, name in candidates if name == name_part]
    matches = exact or [i for i, name in candidates if name_part.lower() in name.lower()]
    if len(matches) != 1:
        raise LookupError(f"{kind} 裝置「{name_part}」符合 {len(matches)} 個：{matches}")
    return matches[0]


class DiscordCapture:
    """只收 Discord process tree 播出嘅聲，轉成 16 kHz mono float32，逐塊交俾 on_audio。"""

    def __init__(self, on_audio: Callable[[np.ndarray], None], process_name: str = "Discord"):
        self._on_audio = on_audio
        self._proc = subprocess.Popen(
            [str(PROC_LOOPBACK), "--name", process_name, "--stdout"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self._resampler = soxr.ResampleStream(CAPTURE_RATE, VAD_RATE, 1, dtype="float32")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        frame_bytes = 2 * 2  # s16le stereo
        chunk = CAPTURE_RATE // 100 * frame_bytes  # 10 ms
        while True:
            data = self._proc.stdout.read(chunk)
            if not data:
                break
            usable = len(data) - len(data) % frame_bytes
            pcm = np.frombuffer(data[:usable], dtype="<i2").reshape(-1, 2).astype(np.float32) / 32768.0
            out = self._resampler.resample_chunk(pcm.mean(axis=1))
            if len(out):
                self._on_audio(out)

    def close(self):
        self._proc.kill()


def ensure_com():
    """WASAPI 要求開 stream 嘅 thread 已初始化 COM；sounddevice 唔會幫背景 thread 做，
    唔做嘅話會報誤導性嘅 WDM-KS「Unanticipated host error」。重複呼叫冇害。"""
    ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED


def output_device_names() -> list[str]:
    hostapis = sd.query_hostapis()
    return [d["name"] for d in sd.query_devices()
            if "WASAPI" in hostapis[d["hostapi"]]["name"] and d["max_output_channels"] > 0]


def default_output_name() -> str | None:
    """Windows 預設輸出裝置（WASAPI）嘅名。"""
    for h in sd.query_hostapis():
        if "WASAPI" in h["name"] and h["default_output_device"] >= 0:
            return sd.query_devices(h["default_output_device"])["name"]
    return None


class Player:
    """AI 聲音輸出：主輸出（虛擬咪，Discord 收到）＋可選監聽輸出（用戶自己聽）。"""

    def __init__(self, device_name: str, monitor_device: str | None = None, monitor_volume: float = 1.0):
        self.main = AudioOut(device_name)
        self.monitor: AudioOut | None = None
        self.monitor_volume = monitor_volume
        self.set_monitor(monitor_device)

    def set_main(self, device_name: str):
        old, self.main = self.main, AudioOut(device_name)
        old.close()

    def set_monitor(self, device_name: str | None):
        old, self.monitor = self.monitor, (AudioOut(device_name) if device_name else None)
        if old:
            old.close()

    @property
    def on_first_sample(self):
        return self.main.on_first_sample

    @on_first_sample.setter
    def on_first_sample(self, callback):
        self.main.on_first_sample = callback

    def enqueue(self, audio: np.ndarray):
        self.main.enqueue(audio)
        if self.monitor:
            self.monitor.enqueue(audio * self.monitor_volume)

    def clear(self):
        self.main.clear()
        if self.monitor:
            self.monitor.clear()

    @property
    def busy(self) -> bool:
        return self.main.busy

    def close(self):
        self.main.close()
        if self.monitor:
            self.monitor.close()


class AudioOut:
    """播音去一個裝置；可以即時清空（打斷）。"""

    def __init__(self, device_name: str):
        self._queue: collections.deque[np.ndarray] = collections.deque()
        self._current: np.ndarray | None = None
        self._pos = 0
        self._lock = threading.Lock()
        self.on_first_sample: Callable[[], None] | None = None
        ensure_com()
        device = find_wasapi_device(device_name, "output")
        self._stream = sd.OutputStream(
            device=device, samplerate=PLAY_RATE, channels=2, dtype="float32", latency="low",
            extra_settings=sd.WasapiSettings(auto_convert=True), callback=self._callback,
        )
        self._stream.start()

    def _callback(self, out, frames, t, status):
        out[:] = 0
        written = 0
        with self._lock:
            while written < frames:
                if self._current is None:
                    if not self._queue:
                        break
                    self._current, self._pos = self._queue.popleft(), 0
                    if self.on_first_sample is not None:
                        callback, self.on_first_sample = self.on_first_sample, None
                        callback()
                n = min(frames - written, len(self._current) - self._pos)
                out[written:written + n, 0] = self._current[self._pos:self._pos + n]
                written += n
                self._pos += n
                if self._pos >= len(self._current):
                    self._current = None
        out[:, 1] = out[:, 0]

    def enqueue(self, audio: np.ndarray):
        with self._lock:
            self._queue.append(audio.astype(np.float32))

    def clear(self):
        with self._lock:
            self._queue.clear()
            self._current = None
            self.on_first_sample = None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._current is not None or bool(self._queue)

    def close(self):
        self._stream.stop()
        self._stream.close()


def now() -> float:
    return time.perf_counter()
