"""用 Silero VAD 判斷對方幾時開始講、幾時講完。"""

from dataclasses import dataclass
from typing import Callable

import numpy as np
import torch
from silero_vad import load_silero_vad

RATE = 16000
CHUNK = 512  # Silero 16 kHz 固定 512 samples（32 ms）
CHUNK_MS = CHUNK * 1000 / RATE


@dataclass
class TurnConfig:
    start_prob: float = 0.5
    end_prob: float = 0.35
    start_ms: float = 96       # 連續講話咁耐先算開始
    end_ms: float = 600        # 靜音咁耐先算講完
    min_speech_ms: float = 300  # 短過呢個長度嘅聲音（咳、「嗯」、提示音）唔當一輪
    barge_in_ms: float = 300    # AI 播音時，對方講超過咁耐先打斷
    preroll_ms: float = 300
    max_turn_s: float = 30


class TurnDetector:
    """逐塊餵 16 kHz 音訊；回調：
    on_speech_start()：確認開始講
    on_barge_in()：講話持續超過 barge_in_ms（用嚟打斷 AI）
    on_turn_end(audio)：講完，audio 係成句（含 pre-roll）
    """

    def __init__(self, on_speech_start: Callable[[], None], on_barge_in: Callable[[], None],
                 on_turn_end: Callable[[np.ndarray], None], config: TurnConfig | None = None):
        self.cfg = config or TurnConfig()
        self._model = load_silero_vad()
        self._on_speech_start, self._on_barge_in, self._on_turn_end = on_speech_start, on_barge_in, on_turn_end
        self._pending = np.zeros(0, dtype=np.float32)
        self._preroll: list[np.ndarray] = []
        self._speech: list[np.ndarray] = []
        self._in_speech = False
        self._run_ms = 0.0       # 連續講話（未確認開始前）
        self._silence_ms = 0.0
        self._speech_ms = 0.0
        self._barged = False

    def feed(self, audio: np.ndarray):
        self._pending = np.concatenate([self._pending, audio])
        while len(self._pending) >= CHUNK:
            chunk, self._pending = self._pending[:CHUNK], self._pending[CHUNK:]
            with torch.no_grad():
                prob = self._model(torch.from_numpy(chunk), RATE).item()
            self._step(chunk, prob)

    def _step(self, chunk: np.ndarray, prob: float):
        cfg = self.cfg
        if not self._in_speech:
            self._preroll.append(chunk)
            if len(self._preroll) * CHUNK_MS > cfg.preroll_ms:
                self._preroll.pop(0)
            self._run_ms = self._run_ms + CHUNK_MS if prob >= cfg.start_prob else 0.0
            if self._run_ms >= cfg.start_ms:
                self._in_speech, self._speech = True, list(self._preroll)
                self._speech_ms, self._silence_ms, self._barged = self._run_ms, 0.0, False
                self._on_speech_start()
            return

        self._speech.append(chunk)
        if prob >= cfg.end_prob:
            self._speech_ms += CHUNK_MS
            self._silence_ms = 0.0
            if not self._barged and self._speech_ms >= cfg.barge_in_ms:
                self._barged = True
                self._on_barge_in()
        else:
            self._silence_ms += CHUNK_MS

        too_long = len(self._speech) * CHUNK_MS >= cfg.max_turn_s * 1000
        if self._silence_ms >= cfg.end_ms or too_long:
            audio = np.concatenate(self._speech)
            speech_ms = self._speech_ms
            self._in_speech, self._run_ms, self._preroll, self._speech = False, 0.0, [], []
            self._model.reset_states()
            if speech_ms >= cfg.min_speech_ms:
                self._on_turn_end(audio)
