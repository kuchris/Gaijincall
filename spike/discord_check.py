"""用 ProcLoopback 只收 Discord 播出嘅聲（對方語音），再用 Qwen3-ASR 辨識。

用法：uv run --extra asr python spike/discord_check.py [--seconds 10]
"""

import models_env  # noqa: F401  # 必須最先 import

import argparse
import subprocess

import librosa
import numpy as np
import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor

from audio_util import OUT_DIR, PROC_LOOPBACK, rms_db

parser = argparse.ArgumentParser()
parser.add_argument("--seconds", type=float, default=10)
args = parser.parse_args()

model_id = "Qwen/Qwen3-ASR-1.7B-hf"
processor = AutoProcessor.from_pretrained(model_id)
model = AutoModelForMultimodalLM.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cuda")
sr = processor.feature_extractor.sampling_rate

OUT_DIR.mkdir(parents=True, exist_ok=True)
wav = OUT_DIR / "discord_check.wav"
print(f">>> 開始收 Discord 聲音 {args.seconds:.0f} 秒，請對方講嘢……", flush=True)
subprocess.run([str(PROC_LOOPBACK), "--name", "Discord", "--out", str(wav), "--seconds", str(args.seconds)], check=True)
print(">>> 收音完成")

audio, _ = librosa.load(wav, sr=sr, mono=True)
peak = 20 * np.log10(np.max(np.abs(audio)) + 1e-12)
print(f"RMS {rms_db(audio):.1f} dBFS，峰值 {peak:.1f} dBFS")
inputs = processor.apply_transcription_request(audio=audio).to(model.device, model.dtype)
out = model.generate(**inputs, max_new_tokens=256)
parsed = processor.decode(out[:, inputs["input_ids"].shape[1]:], return_format="parsed")[0]
print(f"語言：{parsed.get('language')}")
print(f"辨識：{parsed.get('transcription')}")
