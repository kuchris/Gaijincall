"""離線比較：Qwen3-ASR-1.7B（llama.cpp GPU）對 SenseVoice-Small int8（sherpa-onnx CPU，兩個版本）。

量每句耗時、CER、語言判斷、SenseVoice 載入後多用幾多 RAM。樣本：12 句＋每語言 3 句接埋嘅長段。

加雜音：--noise white|babble --snr 10（babble 用其他語言樣本疊埋扮背景人聲）。

用法：uv run --extra asr python spike/sensevoice_bench.py [--noise white|babble] [--snr 10] [--yue-variant]
"""

import argparse
import ctypes
import ctypes.wintypes
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "spike"))

import paths  # noqa: E402,F401

import librosa  # noqa: E402
import numpy as np  # noqa: E402

import jobobject  # noqa: E402
from asr import ASR, ASR_LANGS, to_display  # noqa: E402
from sensevoice import SenseVoice  # noqa: E402
from streaming_asr_bench import cer  # noqa: E402

SPIKE = ROOT / "spike"


class _Mem(ctypes.Structure):
    _fields_ = [("cb", ctypes.wintypes.DWORD), ("PageFaultCount", ctypes.wintypes.DWORD)] + [
        (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                       "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                                       "PagefileUsage", "PeakPagefileUsage")]


def rss_mb() -> float:
    m = _Mem()
    m.cb = ctypes.sizeof(m)
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(_Mem), ctypes.wintypes.DWORD]
    if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(m), m.cb):
        return float("nan")
    return m.WorkingSetSize / 2**20


def add_noise(a: np.ndarray, kind: str, snr_db: float, babble: np.ndarray, rng) -> np.ndarray:
    if kind == "white":
        noise = rng.standard_normal(len(a)).astype(np.float32)
    else:
        start = rng.integers(0, len(babble) - len(a)) if len(babble) > len(a) else 0
        noise = np.resize(babble[start:], len(a))
    gain = np.sqrt(np.mean(a ** 2) / (np.mean(noise ** 2) * 10 ** (snr_db / 10)))
    return (a + gain * noise).astype(np.float32)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--noise", choices=("none", "white", "babble"), default="none")
    parser.add_argument("--snr", type=float, default=10)
    parser.add_argument("--yue-variant", action="store_true", help="連 2025-09-09 粵語微調版一齊測")
    args = parser.parse_args()
    samples = json.loads((SPIKE / "samples.json").read_text(encoding="utf-8"))
    audio = {s["id"]: librosa.load(SPIKE / "out" / "samples" / f"{s['id']}.wav", sr=16000)[0] for s in samples}
    cases = [(s["id"], s["lang"], audio[s["id"]], s["text"]) for s in samples]
    gap = np.zeros(int(0.4 * 16000), dtype=np.float32)
    for lang in ("yue", "cmn", "ja", "en"):
        group = [s for s in samples if s["lang"] == lang]
        joined = np.concatenate([x for s in group for x in (audio[s["id"]], gap)][:-1])
        cases.append((f"{lang}-long", lang, joined, " ".join(s["text"] for s in group)))
    if args.noise != "none":
        rng = np.random.default_rng(0)
        cases = [(cid, lang, add_noise(a, args.noise, args.snr, np.concatenate(
                     [audio[s["id"]] for s in samples if s["lang"] != lang]), rng), ref)
                 for cid, lang, a, ref in cases]
        print(f"雜音 {args.noise}，SNR {args.snr:g} dB")

    engines = []
    jobobject.kill_children_on_exit()  # 中途出錯都唔會留低 llama-server 霸住 VRAM
    qwen = ASR()
    engines.append(("Qwen3-ASR-1.7B GPU", qwen))
    variants = [("2024-07-17", 2), ("2024-07-17", 4)] + ([("2025-09-09-yue", 4)] if args.yue_variant else [])
    for variant, threads in variants:
        before = rss_mb()
        sv = SenseVoice(variant, threads)
        engines.append((f"SenseVoice {variant} CPU×{threads}（+{rss_mb() - before:.0f} MB RAM）", sv))

    summary = []
    try:
        for name, eng in engines:
            print(f"== {name}")
            rows = []
            for cid, lang, a, ref in cases:
                eng.transcribe_raw(a[:16000])
                t = time.perf_counter()
                asr_lang, raw = eng.transcribe_raw(a)
                ms = (time.perf_counter() - t) * 1000
                got = ASR_LANGS.get(asr_lang or "")
                text = to_display(got, raw)
                rows.append({"id": cid, "ms": ms, "cer": cer(text, ref), "lang_ok": got == lang, "long": cid.endswith("-long")})
                print(f"  [{cid}] {ms:4.0f} ms  CER {rows[-1]['cer']:5.1%}  {got or '?'}{'' if got == lang else '✗'}  {text}")
            for kind, rs in (("短句", [r for r in rows if not r["long"]]), ("長段", [r for r in rows if r["long"]])):
                line = (f"{name} {kind}：中位 {statistics.median(r['ms'] for r in rs):.0f} ms，最差 {max(r['ms'] for r in rs):.0f} ms，"
                        f"平均 CER {statistics.mean(r['cer'] for r in rs):.1%}，語言 {sum(r['lang_ok'] for r in rs)}/{len(rs)}")
                for lang in ("yue", "cmn", "ja", "en"):
                    lr = [r for r in rs if r["id"].startswith(lang)]
                    line += f"；{lang} {statistics.mean(r['cer'] for r in lr):.1%}"
                summary.append(line)
    finally:
        qwen.close()
    print("\n".join(["", *summary]))


if __name__ == "__main__":
    main()
