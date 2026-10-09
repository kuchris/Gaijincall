"""第 2 步：本機 LLM 四語言回覆質素同延遲測試（llama.cpp llama-server）。

用法：uv run python spike/llm_bench.py --model models/gguf/Qwen_Qwen3.5-9B-Q4_K_M.gguf
"""

import argparse
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPIKE = ROOT / "spike"
LLAMA_SERVER = ROOT / "tools" / "llama.cpp" / "bin" / "llama-server.exe"
PORT = 8091

# 系統提示用中性英文，語言規則用目標語言自己寫，避免提示語言帶偏回覆語言（例如普通話被帶成粵語）
BASE_PROMPT = (
    "You are a friend chatting by voice; the other person hears your voice. "
    "Reply in one or two short, natural sentences, like a phone call; open with a brief acknowledgement, then get to the point. "
    "No emoji, lists, brackets or Markdown. "
)
LANG_RULES = {
    "yue": "今次一定要用香港粵語口語回覆，用「係、喺、嘅、唔、咗、啲、佢哋、冇、嚟」等口語字，唔好用書面語或者普通話。用繁體字。",
    "cmn": "這次一定要用標準普通話回覆，不要用粵語詞彙（例如「係、嘅、唔、咗、啲」）。用繁體字。",
    "ja": "今回は必ず自然な話し言葉の日本語で返事してください。",
    "en": "This time, reply only in casual spoken English.",
}

# 第一段可以交 TTS 嘅位置：逗號或者句末標點
FIRST_SEGMENT = re.compile(r"[，,。．.！!？?、；;：:]")
YUE_COLLOQUIAL = set("係喺嘅唔咗啲哋冇嚟咁嘢佢睇俾畀攞諗乜嗰呢啱")
YUE_WRITTEN = ["的", "是", "在", "不", "了", "們", "沒有", "這", "那", "什麼", "他們", "給"]


def start_server(model: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        [str(LLAMA_SERVER), "-m", str(model), "-ngl", "99", "-c", "4096", "--port", str(PORT),
         "-fa", "on", "--no-webui", "--cache-reuse", "256"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1) as r:
                if r.status == 200:
                    return proc
        except OSError:
            time.sleep(0.5)
    proc.kill()
    raise TimeoutError("llama-server 180 秒內未就緒")


def chat(lang: str, user_text: str) -> dict:
    body = {
        "messages": [
            {"role": "system", "content": BASE_PROMPT + LANG_RULES[lang]},
            {"role": "user", "content": user_text},
        ],
        "stream": True,
        "max_tokens": 120,
        "temperature": 0.7,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    ttft = first_segment = None
    text = ""
    tokens = 0
    with urllib.request.urlopen(req) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            delta = json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
            if not delta:
                continue
            now = time.perf_counter() - start
            tokens += 1
            ttft = ttft if ttft is not None else now
            text += delta
            if first_segment is None and FIRST_SEGMENT.search(text):
                first_segment = now
    total = time.perf_counter() - start
    return {"ttft_ms": ttft * 1000, "first_segment_ms": (first_segment or total) * 1000,
            "total_ms": total * 1000, "chunks": tokens, "reply": text.strip()}


def yue_score(text: str) -> tuple[int, int]:
    colloquial = sum(text.count(c) for c in YUE_COLLOQUIAL)
    written = sum(text.count(w) for w in YUE_WRITTEN)
    return colloquial, written


parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
args = parser.parse_args()
model = (ROOT / args.model).resolve()

samples = json.loads((SPIKE / "samples.json").read_text(encoding="utf-8"))
server = start_server(model)
try:
    chat("yue", "你好")  # 預熱
    results = []
    for s in samples:
        r = chat(s["lang"], s["text"])
        results.append({**s, **r})
        extra = ""
        if s["lang"] in ("yue", "cmn"):
            c, w = yue_score(r["reply"])
            extra = f"，粵語口語字 {c}／書面字 {w}"
        print(f"[{s['id']}] TTFT {r['ttft_ms']:.0f} ms，第一段 {r['first_segment_ms']:.0f} ms，"
              f"全句 {r['total_ms']:.0f} ms（{r['chunks']} chunks）{extra}")
        print(f"    對方：{s['text']}")
        print(f"    回覆：{r['reply']}")
finally:
    server.kill()

for key in ("ttft_ms", "first_segment_ms", "total_ms"):
    values = sorted(r[key] for r in results)
    print(f"{key}: 中位數 {values[len(values) // 2]:.0f}，最差 {values[-1]:.0f}")
out = SPIKE / "out" / f"llm_{model.stem}.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"結果寫入 {out}")
