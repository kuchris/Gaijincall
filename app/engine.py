"""對話引擎：Discord 對方語音 → VAD → ASR → LLM（逐句）→ OmniVoice → 虛擬咪（＋可選監聽）。

狀態同對話以事件形式發佈俾控制台；唔保存錄音或逐字稿。
"""

import json
import queue
import threading
import time
from dataclasses import asdict, dataclass, field

import numpy as np

from paths import ROOT

LANGS = ("yue", "cmn", "ja", "en")
MAX_HISTORY = 12
# 第一次用每種語言時 LLM 同 TTS 都特別慢（實測第一輪 5 秒），載入時先跑一次
WARMUP = {"yue": "你好呀，食咗飯未？", "cmn": "你好，最近怎麼樣？", "ja": "こんにちは、元気？", "en": "Hey, how's it going?"}
SETTINGS_FILE = ROOT / "config" / "settings.json"


@dataclass
class Settings:
    lang: str = "auto"                                 # auto 或 LANGS 其中一個
    play_device: str = "MOTIV Mix Virtual Input (Shure Virtual Audio)"
    monitor_on: bool = False
    monitor_device: str | None = None                  # None 用 Windows 預設輸出
    monitor_volume: float = 0.8
    end_ms: float = 600

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self):
        SETTINGS_FILE.parent.mkdir(exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class Turn:
    id: int
    audio: np.ndarray
    detected_at: float
    times: dict = field(default_factory=dict)


class Engine:
    """狀態：loading → off ⇄ listening／hearing／thinking／speaking；paused 疊加喺啟用狀態上。"""

    def __init__(self):
        self.settings = Settings.load()
        self.state = "loading"
        self.load_step = ""
        self.enabled = False
        self.paused = False
        self.responding = False
        self.error: str | None = None
        self.lang: str | None = None
        self._pending_lang: str | None = None
        self.history: list[dict] = []
        self._subscribers: list[queue.Queue] = []
        self._sub_lock = threading.Lock()
        self._turns: queue.Queue[Turn] = queue.Queue()
        self._cancel = threading.Event()
        self._turn_id = 0
        self._hearing = False
        self.capture = None
        self.player = None

    # ---------- 事件 ----------
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._sub_lock:
            self._subscribers.append(q)
        q.put(self.snapshot())
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._sub_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def emit(self, event: dict):
        with self._sub_lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass

    def snapshot(self) -> dict:
        return {"type": "state", "state": self.state, "load_step": self.load_step, "enabled": self.enabled,
                "paused": self.paused, "lang": self.lang, "error": self.error, "settings": asdict(self.settings)}

    def _set_state(self, state: str):
        if state != self.state:
            self.state = state
            self.emit(self.snapshot())

    def _refresh_state(self):
        if self.state == "loading":
            return
        if not self.enabled:
            self._set_state("off")
        elif self.paused:
            self._set_state("paused")
        elif self.player and self.player.busy:
            self._set_state("speaking")
        elif self.responding:
            self._set_state("thinking")
        elif self._hearing:
            self._set_state("hearing")
        else:
            self._set_state("listening")

    # ---------- 載入 ----------
    def load(self):
        try:
            from asr import ASR
            from llm import LLM
            from tts import TTS
            from turns import TurnConfig, TurnDetector

            self._step("載入語音辨識（Qwen3-ASR）")
            self.asr = ASR()
            self._step("載入對話模型（Qwen3.5-9B）")
            self.llm = LLM()
            self._step("載入語音合成（OmniVoice）")
            self.tts = TTS()
            self._step("預熱四種語言")
            for lang, text in WARMUP.items():
                for sentence in self.llm.stream_sentences([{"role": "user", "content": text}], lang, threading.Event()):
                    self.tts.synth(sentence, lang)
            self._step("開啟音訊裝置")
            self._open_player()
            self.detector = TurnDetector(self._on_speech_start, self._on_barge_in, self._on_turn_end,
                                         TurnConfig(end_ms=self.settings.end_ms))
            threading.Thread(target=self._respond_loop, daemon=True).start()
            threading.Thread(target=self._state_ticker, daemon=True).start()
            self.load_step = ""
            self.state = "off"
            self.emit(self.snapshot())
        except Exception as e:
            self.error = f"載入失敗：{e!r}"
            self.emit(self.snapshot())
            raise

    def _open_player(self):
        """開唔到裝置唔當載入失敗：記低錯誤，等用戶揀第二個裝置再試。"""
        from audio_io import Player
        if self.player:
            self.player.close()
            self.player = None
        try:
            self.player = Player(self.settings.play_device, self._monitor_device(), self.settings.monitor_volume)
            self.error = None
        except Exception as e:
            self.error = f"開唔到音訊裝置「{self.settings.play_device}」：{e}"

    def _step(self, text: str):
        self.load_step = text
        self.emit(self.snapshot())

    def _monitor_device(self) -> str | None:
        from audio_io import default_output_name
        if not self.settings.monitor_on:
            return None
        return self.settings.monitor_device or default_output_name()

    # ---------- 控制 ----------
    def enable(self, test_wavs: list[str] | None = None):
        if self.state == "loading" or self.enabled:
            return
        if self.player is None:
            self._open_player()
            if self.player is None:
                self.emit(self.snapshot())
                return
        self.enabled, self.paused, self.error = True, False, None
        self.history.clear()
        self.lang = self._pending_lang = None
        if test_wavs:
            threading.Thread(target=self._feed_test_wavs, args=(test_wavs,), daemon=True).start()
        else:
            from audio_io import DiscordCapture
            try:
                self.capture = DiscordCapture(self.detector.feed)
            except Exception as e:
                self.enabled, self.error = False, f"開始收音失敗：{e}"
        self._refresh_state()

    def disable(self):
        if not self.enabled:
            return
        self.enabled = False
        if self.capture:
            self.capture.close()
            self.capture = None
        self._cancel.set()
        if self.player:
            self.player.clear()
        self._hearing = False
        self._refresh_state()

    def set_paused(self, paused: bool):
        if not self.enabled:
            return
        self.paused = paused
        if paused:
            self._cancel.set()
            if self.player:
                self.player.clear()
        self._refresh_state()

    def update_settings(self, changes: dict):
        s = self.settings
        for key, value in changes.items():
            if key in s.__dataclass_fields__:
                setattr(s, key, value)
        if s.lang not in ("auto", *LANGS):
            s.lang = "auto"
        s.monitor_volume = min(max(float(s.monitor_volume), 0.0), 1.5)
        s.end_ms = min(max(float(s.end_ms), 300.0), 1500.0)
        if self.state != "loading":
            if self.player is None or {"play_device", "monitor_on", "monitor_device"} & changes.keys():
                self._open_player()
            if self.player:
                self.player.monitor_volume = s.monitor_volume
            self.detector.cfg.end_ms = s.end_ms
        s.save()
        self.emit(self.snapshot())

    def close(self):
        self.disable()
        for name in ("player", "tts", "llm"):
            obj = getattr(self, name, None)
            if obj:
                obj.close()

    # ---------- VAD 回調（收音 thread）----------
    def _on_speech_start(self):
        self._hearing = True

    def _on_barge_in(self):
        if self.player and not self.paused and (self.player.busy or self.responding):
            self._cancel.set()
            self.player.clear()
            self.emit({"type": "interrupt"})

    def _on_turn_end(self, audio: np.ndarray):
        self._hearing = False
        if self.enabled and not self.paused:
            self._turn_id += 1
            self._turns.put(Turn(self._turn_id, audio, time.perf_counter()))

    def _feed_test_wavs(self, wavs: list[str]):
        """測試模式：按實時速度將樣本餵入 VAD，每段之後留 6 秒靜音。"""
        import librosa
        for wav in wavs:
            audio, _ = librosa.load(wav, sr=16000, mono=True)
            audio = np.concatenate([audio, np.zeros(16000 * 6, dtype=np.float32)])
            start = time.perf_counter()
            for i in range(0, len(audio), 512):
                if not self.enabled:
                    return
                self.detector.feed(audio[i:i + 512])
                time.sleep(max(0.0, start + (i + 512) / 16000 - time.perf_counter()))
        self.emit({"type": "test_done"})

    # ---------- 回覆 ----------
    def _state_ticker(self):
        while True:
            self._refresh_state()
            time.sleep(0.1)

    def _respond_loop(self):
        while True:
            turn = self._turns.get()
            if not self.enabled or self.paused:
                continue
            self.responding = True
            try:
                self._respond(turn)
            except Exception as e:  # 單輪出錯唔好令成個程式停
                self.emit({"type": "turn_error", "id": turn.id, "error": repr(e)})
            finally:
                self.responding = False

    def _choose_lang(self, detected: str | None, text: str) -> str:
        if self.settings.lang != "auto":
            return self.settings.lang
        if detected is None:
            return self.lang or "cmn"
        long_enough = len(text.split()) >= 3 if detected == "en" else len("".join(text.split())) >= 6
        if self.lang is None or detected == self.lang or long_enough:
            self.lang, self._pending_lang = detected, None
        elif detected == self._pending_lang:  # 短句：連續兩輪都係新語言先切換
            self.lang, self._pending_lang = detected, None
        else:
            self._pending_lang = detected
        return self.lang

    def _respond(self, turn: Turn):
        times = turn.times
        detected, text = self.asr.transcribe(turn.audio)
        times["asr"] = time.perf_counter()
        if not text:
            return
        lang = self._choose_lang(detected, text)
        self.emit({"type": "turn_user", "id": turn.id, "detected": detected, "text": text, "reply_lang": lang})
        self.emit(self.snapshot())

        self._cancel = cancel = threading.Event()
        self.player.on_first_sample = lambda: times.setdefault("play", time.perf_counter())
        self.history.append({"role": "user", "content": text})
        spoken: list[str] = []
        for sentence in self.llm.stream_sentences(self.history[-MAX_HISTORY:], lang, cancel):
            times.setdefault("llm_first", time.perf_counter())
            audio = self.tts.synth(sentence, lang)
            times.setdefault("tts_first", time.perf_counter())
            if cancel.is_set():
                break
            if len(audio) == 0:
                continue
            self.player.enqueue(audio)
            spoken.append(sentence)
            self.emit({"type": "turn_reply", "id": turn.id,
                       "text": (" " if lang == "en" else "").join(spoken), "done": False})
        reply = (" " if lang == "en" else "").join(spoken)
        interrupted = cancel.is_set()
        if reply:
            self.history.append({"role": "assistant", "content": reply + ("……" if interrupted else "")})

        deadline = time.perf_counter() + 5
        while "play" not in times and time.perf_counter() < deadline and not cancel.is_set() and reply:
            time.sleep(0.01)
        end_ms = self.detector.cfg.end_ms
        latency = {"vad": end_ms}
        prev = turn.detected_at
        for key in ("asr", "llm_first", "tts_first", "play"):
            if key in times:
                latency[key] = round((times[key] - prev) * 1000)
                prev = times[key]
        if "play" in times:
            latency["total"] = round((times["play"] - turn.detected_at) * 1000 + end_ms)
        self.emit({"type": "turn_reply", "id": turn.id, "text": reply, "done": True,
                   "interrupted": interrupted, "latency": latency})
