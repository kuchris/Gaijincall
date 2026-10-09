"""串流 ASR（app/streaming_asr.py）實時模擬測試。

逐 32 ms 按真實速度餵樣本，量：第一次出字時間、每次辨識耗時、講完時已確定／已顯示幾多、
最後一次辨識（成段重做 vs 填返已確定字）嘅耗時同錯字率。
短句：12 句樣本；長段：每種語言 3 句接埋（中間 0.4 秒靜音）。

兩段式：--partial sensevoice（或 sensevoice-yue）用 SenseVoice（CPU）出臨時字，Qwen3-ASR 出最終。

用法：uv run --extra asr python spike/streaming_asr_bench.py [--step 0.5] [--no-prefill] [--partial qwen|sensevoice|sensevoice-yue]
"""

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import paths  # noqa: E402,F401

import librosa  # noqa: E402
import numpy as np  # noqa: E402
import opencc  # noqa: E402

import jobobject  # noqa: E402
from asr import ASR, ASR_LANGS, to_display  # noqa: E402
from sensevoice import SenseVoice  # noqa: E402
from streaming_asr import StreamingASR  # noqa: E402

SPIKE = ROOT / "spike"
CHUNK = 512
T2S = opencc.OpenCC("t2s")


def norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", T2S.convert(text)).casefold()


def cer(hyp: str, ref: str) -> float:
    h, r = norm(hyp), norm(ref)
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i]
        for j, hc in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / max(1, len(r))


def run(asr: ASR, stream: StreamingASR, updates: list, audio: np.ndarray, ref: str) -> dict:
    updates.clear()
    start = time.perf_counter()
    for i in range(0, len(audio), CHUNK):
        target = start + i / ASR.rate
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        stream.feed(audio[i:i + CHUNK])
    end = time.perf_counter()
    while stream._busy:  # 等最後一次串流辨識完，睇講完嗰刻顯示到幾多
        time.sleep(0.005)
    last = updates[-1][1] if updates else None

    pre_ms = pre_text = None
    if stream.prefill and stream._committed:
        # 同 engine 一樣：唔清空串流，填返已確定嘅字（留最尾幾個畀模型重寫）
        t = time.perf_counter()
        _, pre_text = stream.transcribe(audio, stream._gen)
        pre_ms = (time.perf_counter() - t) * 1000
    end = time.perf_counter()
    final = stream.finish()
    final_ms = (time.perf_counter() - end) * 1000

    first = next((t - start for t, p in updates if p.text and not p.final), None)
    computes = [p.compute_ms for _, p in updates if not p.final]
    return {
        "audio_s": len(audio) / ASR.rate,
        "updates": len(computes),
        "first_s": first,
        "compute_med": statistics.median(computes) if computes else None,
        "compute_max": max(computes) if computes else None,
        "shown_at_end": last.text if last else "",
        "committed_at_end": last.committed if last else "",
        "final": final.text, "final_ms": final_ms, "final_cer": cer(final.text, ref),
        "prefill": pre_text, "prefill_ms": pre_ms, "prefill_cer": cer(pre_text, ref) if pre_text is not None else None,
        "shown_cer_vs_final": cer(last.text if last else "", final.text),
        "shown_cer": cer(last.text if last else "", ref),
        "committed_frac": len(norm(last.committed if last else "")) / max(1, len(norm(final.text))),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", type=float, default=0.5)
    parser.add_argument("--no-prefill", action="store_true")
    parser.add_argument("--partial", default="qwen", choices=("qwen", "sensevoice", "sensevoice-yue"))
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()

    samples = json.loads((SPIKE / "samples.json").read_text(encoding="utf-8"))
    audio = {s["id"]: librosa.load(SPIKE / "out" / "samples" / f"{s['id']}.wav", sr=16000)[0] for s in samples}
    cases = [(s["id"], audio[s["id"]], s["text"]) for s in samples]
    gap = np.zeros(int(0.4 * 16000), dtype=np.float32)
    for lang in ("yue", "cmn", "ja", "en"):
        group = [s for s in samples if s["lang"] == lang]
        joined = np.concatenate([x for s in group for x in (audio[s["id"]], gap)][:-1])
        cases.append((f"{lang}-long", joined, " ".join(s["text"] for s in group)))

    jobobject.kill_children_on_exit()  # 中途出錯都唔會留低 llama-server 霸住 VRAM
    asr = ASR()
    partial = asr
    if args.partial != "qwen":
        partial = SenseVoice("2025-09-09-yue" if args.partial == "sensevoice-yue" else "2024-07-17", args.threads)
    updates: list = []
    stream = StreamingASR(partial, on_update=lambda p: updates.append((time.perf_counter(), p)),
                          step_s=args.step, prefill=not args.no_prefill, final_asr=asr)
    print(f"partial {args.partial}, step {args.step} s, prefill {'on' if stream.prefill else 'off'}")
    results = []
    try:
        run(asr, stream, updates, cases[0][1], cases[0][2])  # 預熱
        for cid, a, ref in cases:
            r = run(asr, stream, updates, a, ref)
            r["id"] = cid
            results.append(r)
            print(f"[{cid}] {r['audio_s']:.1f}s 更新 {r['updates']} 次，第一次出字 {r['first_s'] or 0:.2f}s，"
                  f"每次 {r['compute_med'] or 0:.0f}/{r['compute_max'] or 0:.0f} ms（中位／最大）")
            print(f"    講完時顯示：{r['committed_at_end']}｜{r['shown_at_end'][len(r['committed_at_end']):]}")
            print(f"    最終（重做 {r['final_ms']:.0f} ms，CER {r['final_cer']:.1%}）：{r['final']}")
            if r["prefill"] is not None:
                print(f"    最終（填返 {r['prefill_ms']:.0f} ms，CER {r['prefill_cer']:.1%}）：{r['prefill']}")
            print(f"    講完時已確定 {r['committed_frac']:.0%}，顯示同最終差 {r['shown_cer_vs_final']:.1%}")
    finally:
        stream.close()
        asr.close()

    short = [r for r in results if not r["id"].endswith("-long")]
    long_ = [r for r in results if r["id"].endswith("-long")]
    for name, rs in (("短句", short), ("長段", long_)):
        firsts = [r["first_s"] for r in rs if r["first_s"] is not None]
        pre = [r for r in rs if r["prefill_ms"] is not None]
        print(f"== {name}（{len(rs)}）：第一次出字中位 {statistics.median(firsts):.2f}s；"
              f"辨識中位 {statistics.median(r['compute_med'] for r in rs):.0f} ms、最大 {max(r['compute_max'] for r in rs):.0f} ms；"
              f"講完時已確定中位 {statistics.median(r['committed_frac'] for r in rs):.0%}，"
              f"顯示同最終差平均 {statistics.mean(r['shown_cer_vs_final'] for r in rs):.1%}、對原文 CER {statistics.mean(r['shown_cer'] for r in rs):.1%}")
        print(f"   最終重做：中位 {statistics.median(r['final_ms'] for r in rs):.0f} ms，平均 CER {statistics.mean(r['final_cer'] for r in rs):.1%}")
        if pre:
            print(f"   最終填返：中位 {statistics.median(r['prefill_ms'] for r in pre):.0f} ms，平均 CER {statistics.mean(r['prefill_cer'] for r in pre):.1%}")
    out = SPIKE / "out" / f"streaming_asr_{args.partial}_step{args.step}{'_noprefill' if args.no_prefill else ''}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
