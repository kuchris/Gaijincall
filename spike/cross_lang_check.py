"""檢查「對方講 A 語言、鎖定 B 語言回覆」：ASR → LLM（鎖定語言）→ TTS → 再用 ASR 聽返。

用法：uv run --extra asr python spike/cross_lang_check.py --reply ja cmn-1 cmn-2 cmn-3
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import paths  # noqa: E402,F401  # 必須最先 import

import argparse  # noqa: E402
import threading  # noqa: E402

import librosa  # noqa: E402
import soxr  # noqa: E402

from asr import ASR  # noqa: E402
from llm import LLM  # noqa: E402
from tts import TTS  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--reply", required=True, help="逗號分隔，例如 ja 或 yue,cmn,en")
parser.add_argument("ids", nargs="+")
args = parser.parse_args()

asr, llm, tts = ASR(), LLM(), TTS()
for reply in args.reply.split(","):
    for sid in args.ids:
        audio, _ = librosa.load(ROOT / "spike" / "out" / "samples" / f"{sid}.wav", sr=16000)
        detected, text = asr.transcribe(audio)
        print(f"\n[{sid} → 鎖定 {reply}] 對方（{detected}）：{text}")
        for sentence in llm.stream_sentences([{"role": "user", "content": text}], reply, threading.Event()):
            speech = tts.synth(sentence, reply)
            back_lang, back_text = asr.transcribe(soxr.resample(speech, 48000, 16000))
            print(f"  AI 文字：{sentence}")
            print(f"  合成後聽返（{back_lang}）：{back_text}")
llm.close()
tts.close()
