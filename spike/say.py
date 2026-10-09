"""用 OmniVoice 合成一句做 WAV（48 kHz），再用 play.py 播去虛擬咪。

需要 OmniVoice 環境：
  ../OmniVoice/.venv/Scripts/python.exe spike/say.py --lang zh "黃小旺你好"
  uv run python spike/play.py spike/out/say.wav
"""

import models_env  # noqa: F401  # 必須最先 import

import argparse
import time

import librosa
import numpy as np
import soundfile as sf
import torch
from omnivoice import OmniVoice

parser = argparse.ArgumentParser()
parser.add_argument("text")
parser.add_argument("--lang", default="zh", help="yue／zh／ja／en")
parser.add_argument("--out", default=str(models_env.MODELS_DIR.parent / "spike" / "out" / "say.wav"))
args = parser.parse_args()

model = OmniVoice.from_pretrained(str(models_env.MODELS_DIR / "OmniVoice"), device_map="cuda:0", dtype=torch.float16)
start = time.perf_counter()
audio = model.generate(text=args.text, language=args.lang, instruct="female, young adult", num_step=16)[0]
print(f"合成 {time.perf_counter() - start:.2f} 秒，音訊 {len(audio) / model.sampling_rate:.1f} 秒")
audio = librosa.resample(np.asarray(audio, dtype=np.float32), orig_sr=model.sampling_rate, target_sr=48000)
sf.write(args.out, audio, 48000)
print(f"寫入 {args.out}")
