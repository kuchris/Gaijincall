"""Qwen3-ASR 辨識。"""

import numpy as np
import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor

# Qwen3-ASR 語言名 → 對話語言代碼
ASR_LANGS = {"Cantonese": "yue", "Chinese": "cmn", "Japanese": "ja", "English": "en"}


class ASR:
    def __init__(self, model_id: str = "Qwen/Qwen3-ASR-1.7B-hf"):
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForMultimodalLM.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cuda")
        self.rate = self.processor.feature_extractor.sampling_rate
        self.transcribe(np.zeros(self.rate, dtype=np.float32))  # 預熱

    @torch.inference_mode()
    def transcribe(self, audio: np.ndarray) -> tuple[str | None, str]:
        """回傳（對話語言代碼或 None，文字）。audio 係 16 kHz mono float32。"""
        inputs = self.processor.apply_transcription_request(audio=audio).to(self.model.device, self.model.dtype)
        out = self.model.generate(**inputs, max_new_tokens=200)
        parsed = self.processor.decode(out[:, inputs["input_ids"].shape[1]:], return_format="parsed")[0]
        return ASR_LANGS.get(parsed.get("language") or ""), (parsed.get("transcription") or "").strip()
