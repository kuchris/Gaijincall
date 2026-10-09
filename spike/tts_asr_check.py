"""用 Qwen3-ASR 反向辨識 TTS 輸出，檢查語言判斷同字錯率（CER）。

用法：uv run python spike/tts_asr_check.py spike/out/tts_omnivoice_design_16
"""

import models_env  # noqa: F401  # 必須最先 import

import argparse
import json
import re
import unicodedata
from pathlib import Path

import librosa
import opencc
import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor

EXPECTED_LANG = {"yue": "Cantonese", "cmn": "Chinese", "ja": "Japanese", "en": "English"}
to_simplified = opencc.OpenCC("t2s")

parser = argparse.ArgumentParser()
parser.add_argument("tts_dir")
parser.add_argument("--model", default="Qwen/Qwen3-ASR-1.7B-hf")
args = parser.parse_args()
tts_dir = Path(args.tts_dir)

processor = AutoProcessor.from_pretrained(args.model)
model = AutoModelForMultimodalLM.from_pretrained(args.model, dtype=torch.bfloat16, device_map="cuda")
sr = processor.feature_extractor.sampling_rate


def normalize(text: str, lang: str) -> list[str]:
    text = to_simplified.convert(unicodedata.normalize("NFKC", text)).lower()
    text = re.sub(r"[^\w\s]", "", text)
    # 英文按字詞計（WER），其他按字元計（CER）
    return text.split() if lang == "en" else list(text.replace(" ", ""))


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


timing = json.loads((tts_dir / "timing.json").read_text(encoding="utf-8"))
rows = []
for t in timing:
    audio, _ = librosa.load(tts_dir / f"{t['id']}.wav", sr=sr)
    inputs = processor.apply_transcription_request(audio=audio).to(model.device, model.dtype)
    out = model.generate(**inputs, max_new_tokens=256)
    parsed = processor.decode(out[:, inputs["input_ids"].shape[1]:], return_format="parsed")[0]
    ref, hyp = normalize(t["text"], t["lang"]), normalize(parsed.get("transcription") or "", t["lang"])
    err = edit_distance(ref, hyp) / max(len(ref), 1)
    lang_ok = parsed.get("language") == EXPECTED_LANG[t["lang"]]
    rows.append({**t, "asr_language": parsed.get("language"), "asr_text": parsed.get("transcription"),
                 "error_rate": err, "lang_ok": lang_ok})
    print(f"[{t['id']}] 語言 {parsed.get('language')}{'' if lang_ok else ' ✗'}，錯誤率 {err:.0%}")
    if err > 0.1 or not lang_ok:
        print(f"    原文：{t['text']}")
        print(f"    辨識：{parsed.get('transcription')}")

for lang in EXPECTED_LANG:
    sub = [r for r in rows if r["lang"] == lang]
    print(f"{lang}: 語言正確 {sum(r['lang_ok'] for r in sub)}/{len(sub)}，平均錯誤率 {sum(r['error_rate'] for r in sub) / len(sub):.0%}")
(tts_dir / "asr_check.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
