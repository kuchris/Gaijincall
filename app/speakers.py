"""講者辨識：每句計聲紋（3D-Speaker CAM++ zh_en，sherpa-onnx CPU），即時分組。

實測（spike/speaker_bench.py，5 把唔同聲音）：每句約 18 ms；同一人相似度最低 0.82、唔同人最高 0.45；
門檻 0.5 即時分組全對（ERes2NetV2 較慢較差，英文 WeSpeaker 分唔開）。真人同性別、同語言會難好多，所以預設門檻偏高少少。

聲紋只放記憶體，停 AI 模式就清除，唔寫磁碟。
"""

import threading
from dataclasses import dataclass, field

import numpy as np
import sherpa_onnx

from paths import MODELS_DIR

MODEL = MODELS_DIR / "speaker" / "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
RATE = 16000
MIN_NEW_SPEAKER_S = 1.0   # 短過呢個長度嘅句子聲紋唔可靠：唔開新講者，只歸入最似嗰個
SHORT_MARGIN = 0.1        # 短句歸入現有講者時門檻放寬幾多
MAX_SPEAKERS = 8


@dataclass
class Speaker:
    id: int
    name: str
    centroid: np.ndarray
    count: int = 1
    custom_name: bool = False

    def add(self, emb: np.ndarray):
        self.centroid = self.centroid + (emb - self.centroid) / (self.count + 1)
        self.count += 1


@dataclass
class Match:
    speaker: Speaker | None
    similarity: float
    new: bool = False


@dataclass
class SpeakerTracker:
    threshold: float = 0.55
    speakers: list[Speaker] = field(default_factory=list)

    def __post_init__(self):
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODEL), num_threads=2, provider="cpu")
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self._lock = threading.Lock()
        self._next_id = 1
        self.embed(np.zeros(RATE, dtype=np.float32))  # 預熱

    def embed(self, audio: np.ndarray) -> np.ndarray:
        stream = self._extractor.create_stream()
        stream.accept_waveform(RATE, audio)
        stream.input_finished()
        emb = np.array(self._extractor.compute(stream), dtype=np.float32)
        return emb / (np.linalg.norm(emb) + 1e-9)

    def identify(self, audio: np.ndarray) -> Match:
        emb = self.embed(audio)
        short = len(audio) / RATE < MIN_NEW_SPEAKER_S
        with self._lock:
            best, sim = None, -1.0
            for spk in self.speakers:
                s = float(np.dot(emb, spk.centroid) / (np.linalg.norm(spk.centroid) + 1e-9))
                if s > sim:
                    best, sim = spk, s
            threshold = self.threshold - (SHORT_MARGIN if short else 0.0)
            if best is not None and sim >= threshold:
                if not short:   # 短句唔更新聲紋，避免拉歪
                    best.add(emb)
                return Match(best, sim)
            if short or len(self.speakers) >= MAX_SPEAKERS:
                return Match(None, sim)   # 未知講者
            spk = Speaker(self._next_id, f"Speaker {self._next_id}", emb)
            self._next_id += 1
            self.speakers.append(spk)
            return Match(spk, sim, new=True)

    def rename(self, speaker_id: int, name: str):
        with self._lock:
            for spk in self.speakers:
                if spk.id == speaker_id:
                    spk.name = name.strip()[:30] or f"Speaker {spk.id}"
                    spk.custom_name = bool(name.strip())

    def merge(self, keep_id: int, drop_id: int):
        """將 drop 併入 keep（同一個人被分咗兩組時用）。"""
        with self._lock:
            keep = next((s for s in self.speakers if s.id == keep_id), None)
            drop = next((s for s in self.speakers if s.id == drop_id), None)
            if keep is None or drop is None or keep is drop:
                return
            total = keep.count + drop.count
            keep.centroid = (keep.centroid * keep.count + drop.centroid * drop.count) / total
            keep.count = total
            self.speakers.remove(drop)

    def reset(self):
        with self._lock:
            self.speakers.clear()
            self._next_id = 1

    def summary(self) -> list[dict]:
        with self._lock:
            return [{"id": s.id, "name": s.name, "count": s.count} for s in self.speakers]
