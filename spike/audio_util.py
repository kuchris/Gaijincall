"""第 1 步音訊路由測試共用工具。"""

from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "spike" / "out"
PROC_LOOPBACK = ROOT / "tools" / "ProcLoopback" / "bin" / "Release" / "net9.0-windows" / "ProcLoopback.exe"
SAMPLE_RATE = 48000


def find_wasapi_device(name_part: str, kind: str) -> int:
    """按名稱片段搵 WASAPI 裝置；kind 係 'input' 或 'output'。"""
    hostapis = sd.query_hostapis()
    channel_key = f"max_{kind}_channels"
    matches = [
        i
        for i, d in enumerate(sd.query_devices())
        if "WASAPI" in hostapis[d["hostapi"]]["name"]
        and name_part.lower() in d["name"].lower()
        and d[channel_key] > 0
    ]
    if len(matches) != 1:
        raise LookupError(f"{kind} 裝置「{name_part}」符合 {len(matches)} 個：{matches}")
    return matches[0]


def tone(freq: float, seconds: float, amplitude: float = 0.1) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    fade = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.02)
    return (amplitude * np.sin(2 * np.pi * freq * t) * fade).astype(np.float32)


def log_chirp(f0: float, f1: float, seconds: float, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    k = np.log(f1 / f0) / seconds
    phase = 2 * np.pi * f0 * (np.exp(k * t) - 1) / k
    fade = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.01)
    return (amplitude * np.sin(phase) * fade).astype(np.float32)


def dominant_freq(x: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / SAMPLE_RATE)[np.argmax(spectrum)])


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12))


def find_delay(reference: np.ndarray, recorded: np.ndarray) -> tuple[float, float]:
    """以交叉相關搵 recorded 相對 reference 嘅延遲（秒）及正規化相關峰值。"""
    n = len(reference) + len(recorded)
    size = 1 << (n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(recorded, size) * np.conj(np.fft.rfft(reference, size)), size)
    corr = corr[: len(recorded)]
    lag = int(np.argmax(np.abs(corr)))
    segment = recorded[lag : lag + len(reference)]
    norm = np.sqrt(np.sum(reference**2) * np.sum(segment**2)) + 1e-12
    return lag / SAMPLE_RATE, float(np.abs(corr[lag]) / norm)
