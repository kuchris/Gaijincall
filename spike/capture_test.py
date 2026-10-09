"""驗證 ProcLoopback：本 process 播 440 Hz 測試音，用 process loopback 只收本 process 嘅聲。

用法：uv run python spike/capture_test.py [--device 名稱片段]
"""

import argparse
import os
import subprocess
import time

import sounddevice as sd
import soundfile as sf

from audio_util import OUT_DIR, PROC_LOOPBACK, SAMPLE_RATE, dominant_freq, find_wasapi_device, rms_db, tone

parser = argparse.ArgumentParser()
parser.add_argument("--device", default=None, help="播放裝置名稱片段；預設用系統預設輸出")
args = parser.parse_args()

OUT_DIR.mkdir(parents=True, exist_ok=True)
out_wav = OUT_DIR / "capture_self.wav"
device = find_wasapi_device(args.device, "output") if args.device else None

capture = subprocess.Popen(
    [str(PROC_LOOPBACK), "--pid", str(os.getpid()), "--out", str(out_wav), "--seconds", "4"],
)
time.sleep(0.8)
sd.play(tone(440, 2.0, amplitude=0.05), SAMPLE_RATE, device=device, blocking=True)
capture.wait(timeout=10)

audio, sr = sf.read(out_wav, dtype="float32")
mono = audio.mean(axis=1) if audio.ndim == 2 else audio
print(f"收到 {len(mono) / sr:.2f} 秒，RMS {rms_db(mono):.1f} dBFS，主頻 {dominant_freq(mono):.0f} Hz")
ok = len(mono) > 0 and abs(dominant_freq(mono) - 440) < 5 and rms_db(mono) > -50
print("結果：", "通過" if ok else "失敗")
raise SystemExit(0 if ok else 1)
