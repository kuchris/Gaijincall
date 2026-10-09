"""llama.cpp llama-server 對話模型：串流生成，按句切分，可以中途取消。"""

import json
import re
import subprocess
import threading
import time
import urllib.request
from typing import Iterator

from paths import LLAMA_SERVER, LLM_MODEL

PORT = 8091

# 基本提示用中性英文；語言規則用目標語言寫，避免提示語言帶偏回覆語言
BASE_PROMPT = (
    "You are a friend chatting by voice in a Discord voice channel; the other person hears your voice. "
    "Reply in one or two short, natural sentences, like a phone call; open with a brief acknowledgement, then get to the point. "
    "No emoji, lists, brackets or Markdown. "
)
LANG_RULES = {
    "yue": "今次一定要用香港粵語口語回覆，用「係、喺、嘅、唔、咗、啲、佢哋、冇、嚟」等口語字，唔好用書面語或者普通話。用繁體字。",
    "cmn": "這次一定要用標準普通話回覆，不要用粵語詞彙（例如「係、嘅、唔、咗、啲」）。用繁體字。",
    "ja": "今回は必ず自然な話し言葉の日本語で返事してください。",
    "en": "This time, reply only in casual spoken English.",
}

# 第一段：逗號或句末就交 TTS（要至少幾個字）；之後只喺句末切
FIRST_BREAK = re.compile(r"[，,、。．！!？?；;：:\n]")
SENTENCE_BREAK = re.compile(r"[。．！!？?\n]|[.](?=\s)")
EMOJI_OR_MARKUP = re.compile(r"[*_#`~>\[\]（）()]|[\U0001F000-\U0001FAFF☀-➿]")


class LLM:
    def __init__(self):
        self._proc = subprocess.Popen(
            [str(LLAMA_SERVER), "-m", str(LLM_MODEL), "-ngl", "99", "-c", "8192", "--port", str(PORT),
             "-fa", "on", "--no-webui", "--cache-reuse", "256"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            self._proc.kill()
            raise TimeoutError("llama-server 180 秒內未就緒")
        list(self.stream_sentences([{"role": "user", "content": "hi"}], "en", threading.Event()))  # 預熱

    def stream_sentences(self, history: list[dict], lang: str, cancel: threading.Event) -> Iterator[str]:
        """串流生成回覆，每完成一段就 yield。cancel 設定後即刻停止。"""
        body = {
            "messages": [{"role": "system", "content": BASE_PROMPT + LANG_RULES[lang]}, *history],
            "stream": True,
            "max_tokens": 120,
            "temperature": 0.7,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        buffer, first = "", True
        with urllib.request.urlopen(req) as resp:
            for raw in resp:
                if cancel.is_set():
                    return
                line = raw.decode("utf-8").strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                buffer += json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
                while True:
                    pattern = FIRST_BREAK if first else SENTENCE_BREAK
                    m = pattern.search(buffer, 2 if first else 0)
                    if not m:
                        break
                    segment, buffer = buffer[:m.end()], buffer[m.end():]
                    segment = clean(segment)
                    if segment:
                        first = False
                        yield segment
        if (rest := clean(buffer)) and not cancel.is_set():
            yield rest

    def close(self):
        self._proc.kill()


def clean(text: str) -> str:
    return " ".join(EMOJI_OR_MARKUP.sub("", text).split())
