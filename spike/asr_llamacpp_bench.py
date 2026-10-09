"""比較 Qwen3-ASR：llama.cpp（GGUF Q8_0＋mmproj）對 transformers 版。

用法：uv run --extra asr python spike/asr_llamacpp_bench.py
"""

import base64
import io
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

import librosa
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
SPIKE = ROOT / "spike"
ASR_DIR = ROOT / "models" / "gguf" / "asr"
PORT = 8092

server = subprocess.Popen(
    [str(ROOT / "tools" / "llama.cpp" / "bin" / "llama-server.exe"),
     "-m", str(ASR_DIR / "Qwen3-ASR-1.7B-Q8_0.gguf"), "--mmproj", str(ASR_DIR / "mmproj-Qwen3-ASR-1.7B-Q8_0.gguf"),
     "-ngl", "99", "-c", "4096", "--port", str(PORT), "--no-webui"],
    stdout=subprocess.DEVNULL, stderr=open(SPIKE / "out" / "asr_llamacpp_server.log", "wb"),
)
for _ in range(240):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1) as r:
            if r.status == 200:
                break
    except OSError:
        time.sleep(0.5)


def transcribe(audio_16k) -> tuple[str, float]:
    buf = io.BytesIO()
    sf.write(buf, audio_16k, 16000, format="WAV", subtype="PCM_16")
    body = {
        "messages": [{"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": base64.b64encode(buf.getvalue()).decode(), "format": "wav"}}]}],
        "max_tokens": 200, "temperature": 0,
    }
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    with urllib.request.urlopen(req) as r:
        out = json.loads(r.read())["choices"][0]["message"]["content"]
    return out, (time.perf_counter() - start) * 1000


try:
    samples = json.loads((SPIKE / "samples.json").read_text(encoding="utf-8"))
    hf = {r["id"]: r for r in json.loads((SPIKE / "out" / "asr_Qwen3-ASR-1.7B-hf.json").read_text(encoding="utf-8"))}
    first, _ = librosa.load(SPIKE / "out" / "samples" / f"{samples[0]['id']}.wav", sr=16000)
    transcribe(first)  # 預熱
    times = []
    for s in samples:
        audio, _ = librosa.load(SPIKE / "out" / "samples" / f"{s['id']}.wav", sr=16000)
        out, ms = transcribe(audio)
        times.append(ms)
        m = re.match(r"\s*language\s+(\w+)\s*<asr_text>(.*)", out, re.S)
        lang, text = (m.group(1), m.group(2).strip()) if m else (None, out.strip())
        print(f"[{s['id']}] llama.cpp {ms:.0f} ms（transformers {hf[s['id']]['asr_ms']:.0f} ms），語言 {lang}")
        print(f"    llama.cpp：{text}")
        print(f"    transformers：{hf[s['id']]['transcription']}")
    times.sort()
    print(f"llama.cpp 中位數 {times[len(times) // 2]:.0f} ms，最差 {times[-1]:.0f} ms")
finally:
    server.kill()
