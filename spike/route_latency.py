"""量度虛擬咪路由延遲：用 PortAudio 時間戳比較播放 DAC 時間同錄音 ADC 時間。

用法：uv run python spike/route_latency.py [--play ...] [--record ...] [--repeat 5]
"""

import argparse
import threading
import time

import numpy as np
import sounddevice as sd

from audio_util import SAMPLE_RATE, find_wasapi_device, find_delay, log_chirp

parser = argparse.ArgumentParser()
parser.add_argument("--play", default="MOTIV Mix Virtual Input")
parser.add_argument("--record", default="MOTIV Mix Virtual Output")
parser.add_argument("--repeat", type=int, default=5)
args = parser.parse_args()

play_dev = find_wasapi_device(args.play, "output")
rec_dev = find_wasapi_device(args.record, "input")
signal = log_chirp(300, 6000, 0.3, amplitude=0.3)
wasapi = sd.WasapiSettings(auto_convert=True)

for i in range(args.repeat):
    recorded: list[np.ndarray] = []
    rec_start: list[float] = []
    play_start: list[float] = []
    pos = 0
    done = threading.Event()

    def in_cb(data, frames, t, status):
        if not rec_start:
            rec_start.append(t.inputBufferAdcTime)
        recorded.append(data[:, 0].copy())

    def out_cb(data, frames, t, status):
        global pos
        if not play_start:
            play_start.append(t.outputBufferDacTime)
        chunk = signal[pos:pos + frames]
        data[:] = 0
        data[:len(chunk), 0] = chunk
        if data.shape[1] > 1:
            data[:len(chunk), 1] = chunk
        pos += frames
        if pos >= len(signal) + SAMPLE_RATE // 2:
            done.set()

    with sd.InputStream(device=rec_dev, samplerate=SAMPLE_RATE, channels=2, dtype="float32",
                        extra_settings=wasapi, callback=in_cb):
        time.sleep(0.3)
        with sd.OutputStream(device=play_dev, samplerate=SAMPLE_RATE, channels=2, dtype="float32",
                             extra_settings=wasapi, callback=out_cb):
            done.wait(5)
        time.sleep(0.3)

    rec = np.concatenate(recorded)
    offset, corr = find_delay(signal, rec)
    # 錄音中 chirp 出現時間（ADC 時鐘）減播放第一個 sample 嘅 DAC 時間
    latency = (rec_start[0] + offset) - play_start[0]
    print(f"第 {i + 1} 次：路由延遲 {latency * 1000:.0f} ms（相關度 {corr:.2f}）")
