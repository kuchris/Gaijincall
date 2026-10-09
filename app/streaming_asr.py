"""喺離線 Qwen3-ASR（llama.cpp）上面做串流辨識：講緊嘢期間不斷重新辨識成段聲，即時出臨時文字。

做法同 whisper_streaming 嘅 LocalAgreement-2：
- 每多咗 step_s 秒聲就重新辨識由段頭到而家嘅聲（上一次未完就跳過，永遠用最新嘅聲）。
- 連續兩次結果開頭一致嘅部分當「已確定」，之後唔會再變；後面嘅當「臨時」，下次可能改。
- 已確定嘅字用 assistant prefill 填返入去，模型只生成後面，快啲亦唔會閃。
- finish() 喺講完時用成段聲做最後一次辨識，出最終文字。

唔依賴 Gaijincall 嘅 engine，其他項目（例如會議 app）可以直接用：
    stream = StreamingASR(asr, on_update=print)
    stream.feed(chunk) ... ; result = stream.finish()
一段聲（一句或者 VAD 切出嚟嘅一段）用一次，新一段前 reset()；成本隨段長增加，長會議要按停頓切段。
"""

import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from asr import ASR, ASR_LANGS, to_display

# 比較單位：一個拉丁字／數字詞，或者一個其他字元（中日文逐字、標點）；連前面空白，join 返就係原文
UNIT = re.compile(r"\s*(?:[A-Za-z0-9'’]+|\S)")


def units(text: str) -> list[str]:
    return UNIT.findall(text)


PUNCT = re.compile(r"[^\w\s]")


def _same(a: str, b: str) -> bool:
    a, b = a.strip().casefold(), b.strip().casefold()
    # 標點每次辨識都可能唔同（「Hey.」／「Hey,」），兩個都係標點就當一致
    return a == b or (bool(PUNCT.fullmatch(a)) and bool(PUNCT.fullmatch(b)))


def agreed_prefix(a: list[str], b: list[str]) -> int:
    n = 0
    while n < len(a) and n < len(b) and _same(a[n], b[n]):
        n += 1
    return n


@dataclass
class Partial:
    lang: str | None   # 對話語言代碼（yue／cmn／ja／en），未知係 None
    committed: str     # 已確定，之後唔會變（已轉繁體）
    tentative: str     # 臨時，下次可能改
    audio_s: float     # 呢次結果涵蓋幾多秒聲
    compute_ms: float  # 呢次辨識用咗幾耐
    final: bool = False
    segment: int = 0   # 屬於邊一段（reset() 回傳嘅編號）

    @property
    def text(self) -> str:
        return self.committed + self.tentative


class StreamingASR:
    def __init__(self, asr: ASR, on_update: Callable[[Partial], None] | None = None,
                 step_s: float = 0.5, min_audio_s: float = 0.5, prefill: bool = True, final_asr: ASR | None = None):
        """asr 出臨時字；final_asr（預設同 asr）講完時出最終文字。兩個唔同就係兩段式：
        例如 SenseVoice（CPU）出臨時字、Qwen3-ASR 出最終。"""
        self.asr, self.final_asr, self.on_update = asr, final_asr or asr, on_update
        self.step_s, self.min_audio_s = step_s, min_audio_s
        self.prefill = prefill and getattr(asr, "supports_prefill", True)
        self._cond = threading.Condition()
        self._closed = False
        self._busy = False
        self._holds = 0   # transcribe() 進行中就暫停串流辨識
        with self._cond:
            self._reset_locked()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---- 呼叫方 ----

    def feed(self, audio: np.ndarray):
        """加入 16 kHz mono float32 音訊。"""
        with self._cond:
            self._chunks.append(audio.astype(np.float32, copy=False))
            self._samples += len(audio)
            self._cond.notify_all()

    def finish(self, final_prefill: bool = False) -> Partial:
        """講完：等進行中嘅辨識完成，再用成段聲辨識一次，回傳最終結果，然後清空等下一段。

        final_prefill=False（預設）最後一次唔填已確定嘅字，由模型睇晒成段重新出，最準；
        True 就填返，快少少但已確定嘅錯字改唔到。
        """
        with self._cond:
            self._finishing = True
            while self._busy:
                self._cond.wait()
            audio = self._audio_locked()
            asr_lang, committed = self._asr_lang, self._committed
        if len(audio) == 0:
            result = Partial(None, "", "", 0.0, 0.0, final=True)
        else:
            start = time.perf_counter()
            final = self.final_asr
            if final_prefill and asr_lang and committed and final is self.asr and self.prefill:
                asr_lang, raw = final.transcribe_raw(audio, asr_lang, "".join(committed), self._max_tokens(audio))
            else:
                asr_lang, raw = final.transcribe_raw(audio, max_tokens=self._max_tokens(audio))
            lang = ASR_LANGS.get(asr_lang or "")
            result = Partial(lang, to_display(lang, raw), "", len(audio) / ASR.rate,
                             (time.perf_counter() - start) * 1000, final=True)
        with self._cond:
            self._reset_locked()
        if self.on_update:
            self.on_update(result)
        return result

    def reset(self) -> int:
        """開始新一段（唔等進行中嘅辨識；佢嘅結果會作廢）。回傳新一段嘅編號。"""
        with self._cond:
            self._reset_locked()
            return self._gen

    def transcribe(self, audio: np.ndarray, segment: int) -> tuple[str | None, str]:
        """唔清空串流，攞 audio 嘅最終文字（對話語言代碼，已轉繁體）。

        audio 係第 segment 段由頭到而家嘅聲（例如提早開始時嘅半句）。仲係同一段就填返已確定嘅字，
        只生成後面（約 20 ms）；唔係就成段辨識。期間暫停串流辨識，免得兩個請求爭 GPU。
        """
        with self._cond:
            self._holds += 1
            try:
                while self._busy:
                    self._cond.wait()
                same = segment == self._gen and self.prefill
                asr_lang = self._asr_lang if same else None
                prefix = "".join(self._committed) if asr_lang else ""
            except BaseException:
                self._holds -= 1
                raise
        try:
            got, raw = self.final_asr.transcribe_raw(audio, asr_lang if self.final_asr is self.asr else None,
                                                     prefix, self._max_tokens(audio))
        finally:
            with self._cond:
                self._holds -= 1
                self._cond.notify_all()
        lang = ASR_LANGS.get(got or "")
        return lang, to_display(lang, raw)

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        self._thread.join(timeout=5)

    # ---- 內部 ----

    def _reset_locked(self):
        self._chunks: list[np.ndarray] = []
        self._samples = 0
        self._decoded_samples = 0
        self._asr_lang: str | None = None
        self._committed: list[str] = []
        self._previous: list[str] = []
        self._finishing = False
        self._gen = getattr(self, "_gen", 0) + 1
        self._cond.notify_all()

    def _audio_locked(self) -> np.ndarray:
        if len(self._chunks) > 1:
            self._chunks = [np.concatenate(self._chunks)]
        return self._chunks[0] if self._chunks else np.zeros(0, dtype=np.float32)

    @staticmethod
    def _max_tokens(audio: np.ndarray) -> int:
        return max(200, int(len(audio) / ASR.rate * 15))

    def _due_locked(self) -> bool:
        step = int(self.step_s * ASR.rate)
        return (not self._finishing and not self._holds and self._samples >= self.min_audio_s * ASR.rate
                and self._samples - self._decoded_samples >= step)

    def _run(self):
        while True:
            with self._cond:
                while not self._closed and not self._due_locked():
                    self._cond.wait()
                if self._closed:
                    return
                self._busy = True
                audio = self._audio_locked()
                self._decoded_samples = len(audio)
                gen = self._gen
                asr_lang = self._asr_lang if self.prefill else None
                prefix = "".join(self._committed) if asr_lang else ""
            try:
                start = time.perf_counter()
                got_lang, raw = self.asr.transcribe_raw(audio, asr_lang, prefix, self._max_tokens(audio))
                compute_ms = (time.perf_counter() - start) * 1000
                update = self._update(gen, got_lang, raw, len(audio), compute_ms)
            except OSError:
                update = None  # ASR 伺服器暫時唔得；下一步再試
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()
            if update and self.on_update:
                self.on_update(update)

    def _update(self, gen: int, asr_lang: str | None, raw: str, samples: int, compute_ms: float) -> Partial | None:
        with self._cond:
            if self._finishing or gen != self._gen:  # 期間 finish／reset 咗，結果作廢
                return None
            hyp = units(raw)
            committed = self._committed
            if asr_lang and asr_lang != "None":
                if self._asr_lang is None or not committed:
                    self._asr_lang = asr_lang
                # 同上次一致嘅開頭當已確定（只會加長，唔會縮短）
                agree = agreed_prefix(self._previous, hyp)
                if agree > len(committed) and agreed_prefix(committed, hyp) == len(committed):
                    committed = self._committed = hyp[:agree]
            self._previous = hyp
            tentative = hyp[len(committed):]
            lang = ASR_LANGS.get(self._asr_lang or "")
            committed_text = to_display(lang, "".join(committed))
        return Partial(lang, committed_text, to_display(lang, "".join(tentative)),
                       samples / ASR.rate, compute_ms, segment=gen)
