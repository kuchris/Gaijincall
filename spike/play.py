"""播 WAV 去虛擬咪（預設 MOTIV Mix Virtual Input，Discord 咪揀 MOTIV Mix Virtual Output 就收到）。

用法：uv run python spike/play.py spike/out/say.wav [--device ...]
"""

import argparse

import librosa
import numpy as np
import sounddevice as sd

from audio_util import SAMPLE_RATE, find_wasapi_device

parser = argparse.ArgumentParser()
parser.add_argument("wav")
parser.add_argument("--device", default="MOTIV Mix Virtual Input")
args = parser.parse_args()

audio, _ = librosa.load(args.wav, sr=SAMPLE_RATE, mono=True)
dev = find_wasapi_device(args.device, "output")
sd.play(np.column_stack([audio, audio]), SAMPLE_RATE, device=dev, blocking=True,
        extra_settings=sd.WasapiSettings(auto_convert=True))
print(f"已播 {len(audio) / SAMPLE_RATE:.1f} 秒去 {sd.query_devices(dev)['name']}")
