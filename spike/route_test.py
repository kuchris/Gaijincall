"""驗證虛擬咪路由：播 chirp 入播放裝置，同時喺錄音裝置錄，量延遲、相關度及音量。

用法：uv run python spike/route_test.py [--play "MOTIV Mix Virtual Input"] [--record "MOTIV Mix Virtual Output"]
"""

import argparse
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

from audio_util import OUT_DIR, SAMPLE_RATE, find_delay, find_wasapi_device, log_chirp, rms_db

parser = argparse.ArgumentParser()
parser.add_argument("--play", default="MOTIV Mix Virtual Input")
parser.add_argument("--record", default="MOTIV Mix Virtual Output")
args = parser.parse_args()

play_dev = find_wasapi_device(args.play, "output")
rec_dev = find_wasapi_device(args.record, "input")
rec_channels = sd.query_devices(rec_dev)["max_input_channels"]

signal = log_chirp(200, 8000, 1.0, amplitude=0.3)
recorded: list[np.ndarray] = []

with sd.InputStream(device=rec_dev, samplerate=SAMPLE_RATE, channels=rec_channels, dtype="float32",
                    extra_settings=sd.WasapiSettings(auto_convert=True),
                    callback=lambda data, *_: recorded.append(data.copy())):
    time.sleep(0.5)
    sd.play(signal, SAMPLE_RATE, device=play_dev, blocking=True,
            extra_settings=sd.WasapiSettings(auto_convert=True))
    time.sleep(1.0)

rec = np.concatenate(recorded)
OUT_DIR.mkdir(parents=True, exist_ok=True)
sf.write(OUT_DIR / "route_recorded.wav", rec, SAMPLE_RATE)

mono = rec.mean(axis=1)
# 播放喺錄音開始後約 0.5 秒先發生，延遲以呢個時間點計
delay, corr = find_delay(signal, mono)
segment = mono[int(delay * SAMPLE_RATE) : int(delay * SAMPLE_RATE) + len(signal)]
print(f"錄音 {len(mono) / SAMPLE_RATE:.2f} 秒，整體 RMS {rms_db(mono):.1f} dBFS")
print(f"chirp 出現喺 {delay:.3f} 秒（播放約喺 0.5 秒開始），相關度 {corr:.3f}")
print(f"chirp 段 RMS {rms_db(segment):.1f} dBFS，原始 {rms_db(signal):.1f} dBFS")
ok = corr > 0.5
print("結果：", "通過" if ok else "失敗（錄音裝置收唔到播放裝置嘅聲，或者被改動太多）")
raise SystemExit(0 if ok else 1)
