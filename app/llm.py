"""llama.cpp llama-server 對話模型：串流生成，按句切分，可以中途取消。"""

import json
import re
import threading
import urllib.request
from typing import Iterator

from llama import start_server
from paths import LLM_MODEL

PORT = 8091

# 基本提示用中性英文；語言規則用目標語言寫，避免提示語言帶偏回覆語言
# 系統提示 = 角色提示（personas.build_prompt）＋技術規則＋語言規則。
# 技術規則放喺角色後面，角色設定推翻唔到長度同語言要求。
DEFAULT_PERSONA_PROMPT = "You are a friend chatting by voice in a Discord voice channel.\n"
RULES_PROMPT = (
    "The other person hears your voice. "
    "Talk like a real person on a call: very short turns, then let them speak. "
    "Say at most {n} short sentence(s). No emoji, lists, brackets or Markdown. "
)
# 每種語言用該語言寫長度限制，模型跟得較好
LANG_RULES = {
    "yue": "今次一定要用香港粵語口語回覆，用「係、喺、嘅、唔、咗、啲、佢哋、冇、嚟」等口語字，唔好用書面語或者普通話。用繁體字。每句唔好長過 20 個字。",
    "cmn": "這次一定要用標準普通話回覆，不要用粵語詞彙（例如「係、嘅、唔、咗、啲」）。用繁體字。每句不要超過 20 個字。",
    "ja": "今回は必ず自然な話し言葉の日本語で返事してください。一文は 25 文字以内にしてください。",
    "en": "This time, reply only in casual spoken English. Keep each sentence under 15 words.",
}

# 加喺最後一句對方說話後面（只送 LLM，唔入對話紀錄）。規則淨係放喺系統提示時，
# 對方講另一種語言模型會跟返對方語言（實測鎖定日文、對方講普通話就用普通話答）。
LANG_REMINDER = {
    "yue": "（請用廣東話口語回覆）",
    "cmn": "（請用普通話回覆）",
    "ja": "（必ず日本語で返事してください）",
    "en": "(Reply in English.)",
}

# 第一段：逗號或句末就交 TTS（要至少幾個字）；之後只喺句末切
FIRST_BREAK = re.compile(r"[，,、。．！!？?；;：:\n]")
SENTENCE_BREAK = re.compile(r"[。．！!？?\n]|[.](?=\s)")
SENTENCE_END = re.compile(r"[。．！!？?.\n]\s*$")
EMOJI_OR_MARKUP = re.compile(r"[*_#`~>\[\]（）()]|[\U0001F000-\U0001FAFF☀-➿]")


class LLM:
    def __init__(self):
        self._proc = start_server("llm", PORT, [
            "-m", str(LLM_MODEL), "-ngl", "99", "-c", "8192", "-fa", "on", "--cache-reuse", "256",
        ])
        list(self.stream_sentences([{"role": "user", "content": "hi"}], "en", threading.Event()))  # 預熱

    def stream_sentences(self, history: list[dict], lang: str, cancel: threading.Event,
                         max_sentences: int = 2, persona_prompt: str = "",
                         strip_labels: list[str] | None = None) -> Iterator[str]:
        """串流生成回覆，每完成一段就 yield；講夠 max_sentences 句或者 cancel 設定後即刻停止。
        strip_labels：群組模式下模型有時會模仿對話格式喺開頭加「名字:」，呢啲前綴會刪走唔讀出嚟。"""
        label = None
        if strip_labels:
            names = "|".join(re.escape(n) for n in strip_labels if n)
            label = re.compile(rf"^\s*(?:{names})\s*[:：]\s*", re.IGNORECASE)
        history = [dict(m) for m in history]
        if history and history[-1]["role"] == "user":
            history[-1]["content"] += "\n" + LANG_REMINDER[lang]
        system = (persona_prompt or DEFAULT_PERSONA_PROMPT) + RULES_PROMPT.format(n=max_sentences) + LANG_RULES[lang]
        body = {
            "messages": [{"role": "system", "content": system}, *history],
            "stream": True,
            "max_tokens": 40 * max_sentences,
            "temperature": 0.7,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        buffer, first, sentences = "", True, 0
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
                    ends_sentence = bool(SENTENCE_END.search(segment))
                    if first and label:
                        segment = label.sub("", segment)
                    segment = clean(segment)
                    if segment:
                        first = False
                        yield segment
                    if ends_sentence:
                        sentences += 1
                        if sentences >= max_sentences:  # 硬性限制長度：講夠就停
                            return
        if (rest := clean(buffer)) and not cancel.is_set():
            yield rest

    def should_reply(self, history: list[dict], name: str) -> bool:
        """群組模式：判斷最新一句係咪同 name 講、或者係 name 可以自然回答嘅公開問題。"""
        lines = "\n".join(m["content"] if m["role"] == "user" else f"{name} (you): {m['content']}"
                          for m in history[-8:])
        body = {
            "messages": [
                {"role": "system", "content": "You decide whether a person in a group voice chat should speak next. "
                                              "Answer with only yes or no."},
                {"role": "user", "content": f"Person: {name}\nConversation (latest last):\n{lines}\n\n"
                                            f"Should {name} reply to the latest message now? Say yes only if it is "
                                            f"addressed to {name}, or it is a question or invitation to everyone that "
                                            f"{name} can naturally answer. Otherwise say no."},
            ],
            "max_tokens": 3,
            "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            answer = json.loads(r.read())["choices"][0]["message"]["content"] or ""
        return answer.strip().lower().startswith("yes")

    def close(self):
        self._proc.kill()


def clean(text: str) -> str:
    return " ".join(EMOJI_OR_MARKUP.sub("", text).split())
