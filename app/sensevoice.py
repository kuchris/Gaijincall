"""SenseVoice-Small 辨識（sherpa-onnx，CPU int8）。

非自回歸、約 2 億參數，唔使 VRAM；介面同 asr.ASR.transcribe_raw 一樣，可以直接交畀 StreamingASR 出臨時字。
唔支援 prefill（已確定字照樣靠 LocalAgreement）。
"""

import paths  # noqa: F401

import re

import numpy as np
import sherpa_onnx

from paths import MODELS_DIR

# SenseVoice 語言標籤 → Qwen3-ASR 語言名（同 asr.ASR_LANGS 對應）
LANGS = {"yue": "Cantonese", "zh": "Chinese", "ja": "Japanese", "en": "English", "ko": "Korean"}
CJK_SPACE = re.compile(r"(?<=[^\sA-Za-z0-9.,!?'’])\s+(?=[^\sA-Za-z0-9])")


class SenseVoice:
    rate = 16000
    supports_prefill = False

    def __init__(self, variant: str = "2024-07-17", threads: int = 2):
        model_dir = MODELS_DIR / "sensevoice" / variant
        self._rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_dir / "model.int8.onnx"), tokens=str(model_dir / "tokens.txt"),
            num_threads=threads, use_itn=True, language="auto")
        self.transcribe_raw(np.zeros(self.rate, dtype=np.float32))  # 預熱

    def transcribe_raw(self, audio: np.ndarray, asr_lang: str | None = None, prefix: str = "",
                       max_tokens: int = 0) -> tuple[str | None, str]:
        stream = self._rec.create_stream()
        stream.accept_waveform(self.rate, audio)
        self._rec.decode_stream(stream)
        result = stream.result
        # 日文會喺詞之間加空格（「すみ ません」）；刪走兩邊都係中日文字嘅空格
        text = CJK_SPACE.sub("", result.text.strip())
        return LANGS.get(result.lang.strip("<|>")), text

    def close(self):
        pass
