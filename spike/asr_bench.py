"""第 2 步：Qwen3-ASR 四語言辨識同延遲測試。

用法：uv run python spike/asr_bench.py [--model Qwen/Qwen3-ASR-1.7B-hf]
"""

import models_env  # noqa: F401  # 必須最先 import

import argparse
import json
import time
from pathlib import Path

import librosa
import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor

SPIKE = Path(__file__).resolve().parent

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="Qwen/Qwen3-ASR-1.7B-hf")
args = parser.parse_args()

t0 = time.perf_counter()
processor = AutoProcessor.from_pretrained(args.model)
model = AutoModelForMultimodalLM.from_pretrained(args.model, dtype=torch.bfloat16, device_map="cuda")
print(f"載入 {args.model}：{time.perf_counter() - t0:.1f} 秒，VRAM {torch.cuda.memory_allocated() / 2**30:.2f} GiB")

sampling_rate = processor.feature_extractor.sampling_rate
samples = json.loads((SPIKE / "samples.json").read_text(encoding="utf-8"))


def transcribe(audio):
    inputs = processor.apply_transcription_request(audio=audio).to(model.device, model.dtype)
    output_ids = model.generate(**inputs, max_new_tokens=256)
    return processor.decode(output_ids[:, inputs["input_ids"].shape[1]:], return_format="parsed")[0]


warmup, _ = librosa.load(SPIKE / "out" / "samples" / f"{samples[0]['id']}.wav", sr=sampling_rate)
transcribe(warmup)

results = []
for s in samples:
    audio, _ = librosa.load(SPIKE / "out" / "samples" / f"{s['id']}.wav", sr=sampling_rate)
    torch.cuda.synchronize()
    start = time.perf_counter()
    parsed = transcribe(audio)
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    results.append({**s, "audio_s": len(audio) / sampling_rate, "asr_ms": elapsed * 1000, **parsed})
    print(f"[{s['id']}] {len(audio) / sampling_rate:.1f}s 音訊 → {elapsed * 1000:.0f} ms，語言 {parsed.get('language')!r}")
    print(f"    原文：{s['text']}")
    print(f"    辨識：{parsed.get('transcription')}")

print(f"峰值 VRAM {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB")
out = SPIKE / "out" / f"asr_{args.model.split('/')[-1]}.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"結果寫入 {out}")
