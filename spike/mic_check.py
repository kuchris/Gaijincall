"""錄 Discord 會收到嘅虛擬咪聲音，再用 Qwen3-ASR 辨識，檢查用戶把聲有冇被扭曲。

用法：uv run --extra asr python spike/mic_check.py [--device "MOTIV Mix Virtual Output"] [--seconds 8]
開始後即刻講嘢。
"""

import models_env  # noqa: F401  # 必須最先 import

import argparse

import librosa
import numpy as np
import sounddevice as sd
import soundfile as sf
import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor

from audio_util import OUT_DIR, SAMPLE_RATE, find_wasapi_device, rms_db

parser = argparse.ArgumentParser()
parser.add_argument("--device", default="MOTIV Mix Virtual Output")
parser.add_argument("--seconds", type=float, default=8)
args = parser.parse_args()

model_id = "Qwen/Qwen3-ASR-1.7B-hf"
processor = AutoProcessor.from_pretrained(model_id)
model = AutoModelForMultimodalLM.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cuda")

dev = find_wasapi_device(args.device, "input")
print(f">>> 開始錄音 {args.seconds:.0f} 秒，請講嘢……", flush=True)
rec = sd.rec(int(args.seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=2, device=dev, blocking=True,
             extra_settings=sd.WasapiSettings(auto_convert=True)).mean(axis=1)
print(">>> 錄音完成")

OUT_DIR.mkdir(parents=True, exist_ok=True)
sf.write(OUT_DIR / "mic_check.wav", rec, SAMPLE_RATE)
peak = 20 * np.log10(np.max(np.abs(rec)) + 1e-12)
print(f"RMS {rms_db(rec):.1f} dBFS，峰值 {peak:.1f} dBFS{'（可能爆音）' if peak > -0.5 else ''}")

audio = librosa.resample(rec, orig_sr=SAMPLE_RATE, target_sr=processor.feature_extractor.sampling_rate)
inputs = processor.apply_transcription_request(audio=audio).to(model.device, model.dtype)
out = model.generate(**inputs, max_new_tokens=256)
parsed = processor.decode(out[:, inputs["input_ids"].shape[1]:], return_format="parsed")[0]
print(f"語言：{parsed.get('language')}")
print(f"辨識：{parsed.get('transcription')}")
