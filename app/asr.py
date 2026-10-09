"""Qwen3-ASR 辨識（llama.cpp llama-server，GGUF Q8_0＋音訊 mmproj）。

實測同 transformers 版輸出一樣，但每句由約 480 ms 減到約 100 ms（transformers 逐 token 嘅 Python 開銷大）。
"""

import base64
import io
import json
import re
import urllib.request

import numpy as np
import opencc
import soundfile as sf

from llama import model_path, start_server

PORT = 8092
# Qwen3-ASR 語言名 → 對話語言代碼
ASR_LANGS = {"Cantonese": "yue", "Chinese": "cmn", "Japanese": "ja", "English": "en"}
# Qwen3-ASR 中文輸出簡體；轉繁體方便顯示，亦同 LLM 用繁體回覆一致（s2t 會將「吃」轉成「喫」，所以普通話用 s2tw）
TO_TRADITIONAL = {"yue": opencc.OpenCC("s2hk"), "cmn": opencc.OpenCC("s2tw")}
OUTPUT = re.compile(r"\s*language\s+(\w+)\s*<asr_text>(.*)", re.S)


def to_display(lang: str | None, text: str) -> str:
    return TO_TRADITIONAL[lang].convert(text) if lang in TO_TRADITIONAL else text


class ASR:
    rate = 16000

    def __init__(self):
        self._proc = start_server("asr", PORT, [
            "-m", model_path("gguf", "asr", "Qwen3-ASR-1.7B-Q8_0.gguf"),
            "--mmproj", model_path("gguf", "asr", "mmproj-Qwen3-ASR-1.7B-Q8_0.gguf"),
            "-ngl", "99", "-c", "4096",
        ])
        self.transcribe(np.zeros(self.rate, dtype=np.float32))  # 預熱

    def transcribe(self, audio: np.ndarray) -> tuple[str | None, str]:
        """回傳（對話語言代碼或 None，文字）。audio 係 16 kHz mono float32。"""
        asr_lang, text = self.transcribe_raw(audio)
        lang = ASR_LANGS.get(asr_lang or "")
        return lang, to_display(lang, text)

    def transcribe_raw(self, audio: np.ndarray, asr_lang: str | None = None, prefix: str = "",
                       max_tokens: int = 200) -> tuple[str | None, str]:
        """回傳（Qwen3-ASR 語言名或 None，未轉繁體嘅原始文字）。

        畀 asr_lang 就用 assistant prefill 固定語言同開頭 prefix（原始文字），模型只生成後面，
        所以串流時已確定嘅字唔會再變，亦少生成啲 token。
        """
        buf = io.BytesIO()
        sf.write(buf, audio, self.rate, format="WAV", subtype="PCM_16")
        messages = [{"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": base64.b64encode(buf.getvalue()).decode(), "format": "wav"}},
        ]}]
        head = f"language {asr_lang}<asr_text>{prefix}" if asr_lang else ""
        if head:
            messages.append({"role": "assistant", "content": head})
        body = {"messages": messages, "max_tokens": max_tokens, "temperature": 0}
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            content = json.loads(r.read())["choices"][0]["message"]["content"] or ""
        if head and not content.startswith(head):  # llama-server 一般會連 prefill 一齊回傳；保險起見補返
            content = head + content
        m = OUTPUT.match(content)
        if not m:
            return None, ""
        return m.group(1), m.group(2).strip()

    def close(self):
        self._proc.kill()
