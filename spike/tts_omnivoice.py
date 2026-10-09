"""第 2 步：OmniVoice 四語言合成延遲測試。輸入用 LLM 9B 嘅實際回覆。

需要 OmniVoice 環境：
  ../OmniVoice/.venv/Scripts/python.exe spike/tts_omnivoice.py [--num-step 16]
輸出：spike/out/tts_omnivoice_<模式>_<step>/<id>.wav 及 timing.json
"""

import models_env  # noqa: F401  # 必須最先 import

import argparse
import json
import re
import time
from pathlib import Path

import soundfile as sf
import torch
from omnivoice import OmniVoice

SPIKE = Path(__file__).resolve().parent
LANG_IDS = {"yue": "yue", "cmn": "zh", "ja": "ja", "en": "en"}
FIRST_SEGMENT = re.compile(r"^.*?[，,。．.！!？?、；;：:]")

parser = argparse.ArgumentParser()
parser.add_argument("--num-step", type=int, default=32)
parser.add_argument("--mode", choices=["design", "clone-yue"], default="design",
                    help="design：voice design；clone-yue：廣東話句子用 SAPI Tracy 參考聲複製")
args = parser.parse_args()

replies = json.loads((SPIKE / "out" / "llm_Qwen_Qwen3.5-9B-Q4_K_M.json").read_text(encoding="utf-8"))
samples = {s["id"]: s for s in json.loads((SPIKE / "samples.json").read_text(encoding="utf-8"))}
out_dir = SPIKE / "out" / f"tts_omnivoice_{args.mode}_{args.num_step}"
out_dir.mkdir(parents=True, exist_ok=True)

t0 = time.perf_counter()
model = OmniVoice.from_pretrained(str(models_env.MODELS_DIR / "OmniVoice"), device_map="cuda:0", dtype=torch.float16)
print(f"載入：{time.perf_counter() - t0:.1f} 秒，VRAM {torch.cuda.memory_allocated() / 2**30:.2f} GiB")

clone_prompt = None
if args.mode == "clone-yue":
    ref = samples["yue-2"]
    clone_prompt = model.create_voice_clone_prompt(ref_audio=str(SPIKE / "out" / "samples" / "yue-2.wav"), ref_text=ref["text"])


def synth(text: str, lang: str) -> tuple[float, object]:
    kwargs = {"num_step": args.num_step}
    if clone_prompt is not None and lang == "yue":
        kwargs["voice_clone_prompt"] = clone_prompt
    else:
        kwargs["instruct"] = "female, young adult"
    torch.cuda.synchronize()
    start = time.perf_counter()
    audio = model.generate(text=text, language=LANG_IDS[lang], **kwargs)[0]
    torch.cuda.synchronize()
    return (time.perf_counter() - start) * 1000, audio


synth("你好，測試一下。", "cmn")  # 預熱
results = []
for r in replies:
    text = " ".join(r["reply"].split())
    m = FIRST_SEGMENT.match(text)
    first = m.group(0) if m else text
    first_ms, first_audio = synth(first, r["lang"])
    full_ms, full_audio = synth(text, r["lang"])
    sf.write(out_dir / f"{r['id']}.wav", full_audio, model.sampling_rate)
    sf.write(out_dir / f"{r['id']}_first.wav", first_audio, model.sampling_rate)
    dur = len(full_audio) / model.sampling_rate
    results.append({"id": r["id"], "lang": r["lang"], "text": text, "first_text": first,
                    "first_ms": first_ms, "full_ms": full_ms, "audio_s": dur})
    print(f"[{r['id']}] 第一段「{first}」{first_ms:.0f} ms；全句 {full_ms:.0f} ms／{dur:.1f}s 音訊（RTF {full_ms / 1000 / dur:.2f}）")

print(f"峰值 VRAM {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB")
firsts = sorted(x["first_ms"] for x in results)
print(f"第一段中位數 {firsts[len(firsts) // 2]:.0f} ms，最差 {firsts[-1]:.0f} ms")
(out_dir / "timing.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
