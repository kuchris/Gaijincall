"""對話引擎：Discord 對方語音 → VAD → ASR → LLM（逐句）→ OmniVoice → 虛擬咪（＋可選監聽）。

狀態同對話以事件形式發佈俾控制台；唔保存錄音或逐字稿。

提早開始：對方靜音達 early_ms 就開始 ASR／LLM／TTS，但要等靜音達 end_ms（確認講完）先顯示同播放；
期間對方再講就靜靜雞作廢（VAD 會累積成句，下次停口連前半句一齊辨識）。
"""

import json
import queue
import threading
import time
from dataclasses import asdict, dataclass, field

import numpy as np
import opencc

import personas as P
from paths import ROOT

_T2S = opencc.OpenCC("t2s")

LANGS = ("yue", "cmn", "ja", "en")
MAX_HISTORY = 12
GROUP_HISTORY = 20       # 群組模式對話較多（包括唔關你事嘅句子），保留多啲上下文
OPEN_WAIT_S = 1.2        # 公開問題：等咁耐都冇人接話，AI 先考慮回答
GROUP_REPLY = ("name", "open")
# 第一次用每種語言時 LLM 同 TTS 都特別慢（實測第一輪 5 秒），載入時先跑一次
WARMUP = {"yue": "你好呀，食咗飯未？", "cmn": "你好，最近怎麼樣？", "ja": "こんにちは、元気？", "en": "Hey, how's it going?"}
SETTINGS_FILE = ROOT / "config" / "settings.json"
# AI 未出聲（仲準備緊）時對方再講咁耐，當佢未講完：取消今次回覆，同下一句合併
CONTINUE_MS = 300
# 試聽聲線用嘅句子
PREVIEW_TEXT = {"yue": "你好呀，我而家把聲係咁樣㗎。", "cmn": "你好，這是我現在的聲音。",
                "ja": "こんにちは、今の声はこんな感じです。", "en": "Hi, this is how I sound right now."}
# 提早開始：比 end_ms 早幾多開始準備（太早會多咗作廢嘅計算，佔住 GPU）
EARLY_LEAD_MS = 300
MIN_EARLY_MS = 200


@dataclass
class Settings:
    lang: str = "auto"                                 # auto 或 LANGS 其中一個
    play_device: str = "MOTIV Mix Virtual Input (Shure Virtual Audio)"
    monitor_on: bool = False
    monitor_device: str | None = None                  # None 用 Windows 預設輸出
    monitor_volume: float = 0.8
    end_ms: float = 600
    barge_in_ms: float = 700     # AI 講緊嘢時，對方要講咁耐先打斷（短嘅「嗯」「哦」、笑聲唔會打斷）
    max_sentences: int = 2       # AI 每次最多講幾句
    persona: str = "natural"     # 性格（app/personas/、config/personas/）
    group_mode: bool = False     # 多人：只喺有人叫你（或者冇人答嘅公開問題）先回應
    group_reply: str = "name"    # name：只回應叫名；open：叫名或者冇人答嘅公開問題
    speaker_threshold: float = 0.55   # 講者聲紋相似度門檻：太低會將唔同人當同一個，太高同一人會分開

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, keep: dict | None = None):
        """keep：臨時覆蓋咗嘅欄位，寫入檔案時用返佢哋原本嘅值。"""
        SETTINGS_FILE.parent.mkdir(exist_ok=True)
        data = {**asdict(self), **(keep or {})}
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def early_ms_for(end_ms: float) -> float:
    return max(MIN_EARLY_MS, end_ms - EARLY_LEAD_MS)


@dataclass
class Turn:
    id: int
    audio: np.ndarray
    started_at: float                  # 開始處理（提早開始時係停口 early_ms 後）
    times: dict = field(default_factory=dict)
    cancel: threading.Event = field(default_factory=threading.Event)
    confirmed: threading.Event = field(default_factory=threading.Event)   # 確認對方講完
    confirmed_at: float = 0.0
    cancel_reason: str | None = None   # continue（對方未講完）、barge（對方打斷）、stop（暫停／停止）、resume（提早開始作廢）
    barge_ms: float = 0.0

    def stop(self, reason: str, speech_ms: float = 0.0):
        if not self.cancel.is_set():
            self.cancel_reason, self.barge_ms = reason, speech_ms
            self.cancel.set()

    def confirm(self):
        self.confirmed_at = time.perf_counter()
        self.confirmed.set()

    def wait_confirmed(self) -> bool:
        """等確認講完；作廢就回傳 False。"""
        while not self.confirmed.wait(0.01):
            if self.cancel.is_set():
                return False
        return not self.cancel.is_set()


class Engine:
    """狀態：loading → off ⇄ listening／hearing／thinking／speaking；paused 疊加喺啟用狀態上。"""

    def __init__(self):
        self.settings = Settings.load()
        self.personas = P.load_personas()
        self.profile = P.load_profile()
        if self.settings.persona not in self.personas:
            self.settings.persona = "natural"
        self._saved_originals: dict = {}   # 臨時覆蓋（例如測試）前嘅值，唔會被覆蓋值寫走
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
        self._current: Turn | None = None
        self._early: Turn | None = None   # 提早開始、未確認講完嘅一輪
        self._carry = ""   # 對方未講完被合併嘅上一段文字
        self._turn_id = 0
        self._hearing = False
        self._utt_over_ai = False
        self._utt_barged = False
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

    # ---------- 角色 ----------
    @property
    def persona(self) -> P.Persona:
        return self.personas.get(self.settings.persona) or next(iter(self.personas.values()))

    def personas_info(self) -> dict:
        return {"personas": [asdict(p) for p in self.personas.values()], "profile": asdict(self.profile),
                "active": self.persona.id, "voice_choices": P.VOICE_CHOICES, "speed_range": P.SPEED_RANGE,
                "defaults": sorted(f.stem for f in P.DEFAULT_DIR.glob("*.json"))}

    def _reset_conversation(self):
        self._stop_all("stop")
        self.history.clear()
        self._carry = ""

    # ---------- 講者 ----------
    def _emit_speakers(self):
        tracker = getattr(self, "speakers", None)
        self.emit({"type": "speakers", "speakers": tracker.summary() if tracker else []})

    def speakers_info(self) -> dict:
        tracker = getattr(self, "speakers", None)
        return {"speakers": tracker.summary() if tracker else []}

    def rename_speaker(self, speaker_id: int, name: str):
        self.speakers.rename(speaker_id, name)
        self._emit_speakers()

    def merge_speakers(self, keep_id: int, drop_id: int):
        self.speakers.merge(keep_id, drop_id)
        self._emit_speakers()

    def reset_speakers(self):
        self.speakers.reset()
        self._emit_speakers()

    def _addressed(self, text: str) -> bool:
        """有冇叫你個名／暱稱（統一簡體、細楷、去空格先比較）。"""
        # 「亞明」「阿明」係同一個叫法（t2s 唔會轉）
        norm = lambda s: _T2S.convert("".join(s.split())).casefold().replace("亚", "阿")
        target = norm(text)
        return any(norm(a) in target for a in self.profile.aliases() if a.strip())

    def _quiet_for(self, seconds: float, turn: Turn) -> bool:
        """等 seconds 秒，期間冇人開口、冇新一輪先回傳 True。"""
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            if self._hearing or not self._turns.empty() or turn.cancel.is_set() or not self.enabled:
                return False
            time.sleep(0.05)
        return True

    def save_persona(self, data: dict):
        persona = P.save_persona(data)
        self.personas = P.load_personas()
        if persona.id == self.settings.persona:
            self._reset_conversation()
        self.emit({"type": "personas", **self.personas_info()})

    def reset_persona(self, persona_id: str):
        P.reset_persona(persona_id)
        self.personas = P.load_personas()
        self.emit({"type": "personas", **self.personas_info()})

    def save_profile(self, data: dict):
        self.profile = P.save_profile(data)
        self._reset_conversation()
        self.emit({"type": "personas", **self.personas_info()})

    def preview_voice(self, persona_id: str, lang: str, voice: dict | None = None):
        """喺監聽裝置（或 Windows 預設輸出）播一句試聽，唔會送去 Discord。"""
        if self.state == "loading" or lang not in LANGS:
            return
        base = self.personas.get(persona_id) or self.persona
        v = P.clean_persona(P.Persona(id=base.id, label=base.label,
                                      voice=P.Voice(**{**asdict(base.voice), **(voice or {})}))).voice

        def run():
            from audio_io import AudioOut, default_output_name
            try:
                audio = self.tts.synth(PREVIEW_TEXT[lang], lang, v.instruct(), v.speed)
                out = AudioOut(self.settings.monitor_device or default_output_name())
                out.enqueue(audio)
                time.sleep(0.2)
                while out.busy:
                    time.sleep(0.1)
                time.sleep(0.3)
                out.close()
            except Exception as e:
                self.error = f"Voice preview failed: {e}"
                self.emit(self.snapshot())
        threading.Thread(target=run, daemon=True).start()

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
        elif self._hearing:
            self._set_state("hearing")
        elif self.responding:
            self._set_state("thinking")
        else:
            self._set_state("listening")

    # ---------- 載入 ----------
    def load(self):
        try:
            from asr import ASR
            from llm import LLM
            from tts import TTS
            from turns import TurnConfig, TurnDetector

            self._step("Loading speech recognition (Qwen3-ASR)")
            self.asr = ASR()
            self._step("Loading language model (Qwen3.5-9B)")
            self.llm = LLM()
            self._step("Loading speech synthesis (OmniVoice)")
            self.tts = TTS()
            self._step("Warming up all four languages")
            for lang, text in WARMUP.items():
                for sentence in self.llm.stream_sentences([{"role": "user", "content": text}], lang, threading.Event()):
                    self.tts.synth(sentence, lang)
            self._step("Loading speaker recognition (CAM++)")
            from speakers import SpeakerTracker
            self.speakers = SpeakerTracker(self.settings.speaker_threshold)
            self._step("Opening audio devices")
            self._open_player()
            self.detector = TurnDetector(
                self._on_speech_start, self._on_speech, self._on_turn_end,
                TurnConfig(end_ms=self.settings.end_ms, early_ms=early_ms_for(self.settings.end_ms)),
                on_pause=self._on_pause, on_resume=self._on_resume, on_discard=self._on_discard,
            )
            threading.Thread(target=self._respond_loop, daemon=True).start()
            threading.Thread(target=self._state_ticker, daemon=True).start()
            self.load_step = ""
            self.state = "off"
            self.emit(self.snapshot())
        except Exception as e:
            self.error = f"Loading failed: {e!r}"
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
            self.error = f"Cannot open audio device \"{self.settings.play_device}\": {e}"

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
        self._carry = ""
        self.reset_speakers()   # 聲紋只屬今次 session
        if test_wavs:
            threading.Thread(target=self._feed_test_wavs, args=(test_wavs,), daemon=True).start()
        else:
            from audio_io import DiscordCapture
            try:
                self.capture = DiscordCapture(self.detector.feed)
            except Exception as e:
                self.enabled, self.error = False, f"Cannot start Discord capture: {e}"
        self._refresh_state()

    def disable(self):
        if not self.enabled:
            return
        self.enabled = False
        if self.capture:
            self.capture.close()
            self.capture = None
        self._stop_all("stop")
        self._hearing = False
        if getattr(self, "speakers", None):
            self.reset_speakers()   # 停 AI 模式即刻清除聲紋
        self._refresh_state()

    def set_paused(self, paused: bool):
        if not self.enabled:
            return
        self.paused = paused
        if paused:
            self._stop_all("stop")
        self._refresh_state()

    def override_settings(self, **values):
        """只喺今次運行生效，唔寫入設定檔（除非之後用戶喺控制台再改呢啲欄位）。"""
        for key, value in values.items():
            self._saved_originals.setdefault(key, getattr(self.settings, key))
            setattr(self.settings, key, value)

    def update_settings(self, changes: dict):
        s = self.settings
        for key, value in changes.items():
            if key in s.__dataclass_fields__:
                setattr(s, key, value)
                self._saved_originals.pop(key, None)
        if s.lang not in ("auto", *LANGS):
            s.lang = "auto"
        s.monitor_volume = min(max(float(s.monitor_volume), 0.0), 1.5)
        s.end_ms = min(max(float(s.end_ms), 300.0), 1500.0)
        s.barge_in_ms = min(max(float(s.barge_in_ms), 300.0), 2000.0)
        s.max_sentences = min(max(int(s.max_sentences), 1), 3)
        if s.persona not in self.personas:
            s.persona = "natural"
        if s.group_reply not in GROUP_REPLY:
            s.group_reply = "name"
        s.group_mode = bool(s.group_mode)
        s.speaker_threshold = round(min(max(float(s.speaker_threshold), 0.3), 0.85), 2)
        if "persona" in changes:
            self._reset_conversation()
        if self.state != "loading":
            self.speakers.threshold = s.speaker_threshold
            if self.player is None or {"play_device", "monitor_on", "monitor_device"} & changes.keys():
                self._open_player()
            if self.player:
                self.player.monitor_volume = s.monitor_volume
            self.detector.cfg.end_ms = s.end_ms
            self.detector.cfg.early_ms = early_ms_for(s.end_ms)
        s.save(self._saved_originals)
        self.emit(self.snapshot())

    def close(self):
        self.disable()
        for name in ("player", "tts", "llm", "asr"):
            obj = getattr(self, name, None)
            if obj:
                obj.close()

    # ---------- VAD 回調（收音 thread）----------
    def _on_speech_start(self):
        self._hearing = True
        # AI 講緊嘢時開始嘅說話：未夠打斷門檻就當附和（「嗯」「哦」、笑聲），唔回應
        self._utt_over_ai = bool(self.player and self.player.busy)
        self._utt_barged = False

    def _stop_all(self, reason: str):
        for turn in (self._current, self._early):
            if turn:
                turn.stop(reason)
        self._early = None
        if self.player:
            self.player.clear()

    def _on_speech(self, speech_ms: float):
        """對方講緊嘢：AI 講緊就要講夠 barge_in_ms 先打斷；AI 未出聲就當對方未講完。"""
        if self.paused or self.player is None:
            return
        turn = self._current
        if self.player.busy:
            if speech_ms >= self.settings.barge_in_ms and not self._utt_barged:
                self._utt_barged = True
                self.player.clear()
                if turn:
                    already_reported = "play" in turn.times and not self.responding
                    turn.stop("barge", speech_ms)
                    if already_reported:
                        # 回覆已經講完生成、播緊時被打斷：補報，並喺對話紀錄標記未講完
                        if self.history and self.history[-1]["role"] == "assistant":
                            self.history[-1]["content"] += "……"
                        self.emit({"type": "turn_interrupted", "id": turn.id, "barge_ms": round(speech_ms)})
            return
        if (turn and not turn.cancel.is_set() and turn.confirmed.is_set() and self.responding
                and "play" not in turn.times and speech_ms >= CONTINUE_MS):
            turn.stop("continue", speech_ms)
            self.player.clear()

    def _is_backchannel(self) -> bool:
        return self._utt_over_ai and not self._utt_barged

    def _new_turn(self, audio: np.ndarray) -> Turn:
        self._turn_id += 1
        turn = Turn(self._turn_id, audio, time.perf_counter())
        self._turns.put(turn)
        return turn

    def _on_pause(self, audio: np.ndarray):
        if self.enabled and not self.paused and not self._is_backchannel():
            self._early = self._new_turn(audio)

    def _on_resume(self):
        if self._early:
            self._early.stop("resume")
            self._early = None

    def _on_discard(self):
        self._hearing = False

    def _on_turn_end(self, audio: np.ndarray):
        self._hearing = False
        if not self.enabled or self.paused:
            return
        early, self._early = self._early, None
        if self._is_backchannel():
            if early:
                early.stop("resume")
            return
        if early and not early.cancel.is_set():
            early.confirm()
        else:
            self._new_turn(audio).confirm()

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
            if not self.enabled or self.paused or turn.cancel.is_set():
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
        self._current = turn
        times = turn.times
        detected, text = self.asr.transcribe(turn.audio)
        times["asr"] = time.perf_counter()
        if not text or turn.cancel.is_set():
            return
        match = self.speakers.identify(turn.audio)   # 約 20 ms（CPU）
        speaker = match.speaker.name if match.speaker else None
        if match.new:
            self._emit_speakers()
        if self._carry:  # 上一段對方未講完，同今段合併
            text = self._carry + (" " if detected == "en" else "") + text
        group = self.settings.group_mode
        history_len = GROUP_HISTORY if group else MAX_HISTORY
        # 語言選擇有狀態（短句連續兩輪先切換），要等確認先決定；未確認前用估計
        lang = self.settings.lang if self.settings.lang != "auto" else (detected or self.lang or "cmn")
        user_msg = {"role": "user", "content": f"{speaker or 'Someone'}: {text}" if group else text}
        spoken: list[str] = []
        held: list[np.ndarray] = []   # 未確認講完前合成好嘅聲音

        if group and not self._addressed(text):
            # 群組模式、冇人叫你：等確認講完，記入對話（俾之後回覆做上下文），通常唔回應
            if not turn.wait_confirmed() and not turn.confirmed.is_set():
                return
            times["confirmed"] = turn.confirmed_at
            self._carry = ""
            lang = self._choose_lang(detected, text)
            self.history.append(user_msg)
            self.emit({"type": "turn_user", "id": turn.id, "detected": detected, "text": text,
                       "reply_lang": lang, "speaker": speaker})
            reply = (self.settings.group_reply == "open" and self._quiet_for(OPEN_WAIT_S, turn)
                     and self.llm.should_reply(self.history[-history_len:], self.profile.name or "me"))
            if not reply or turn.cancel.is_set():
                self.emit({"type": "turn_reply", "id": turn.id, "text": "", "done": True, "interrupted": "listen"})
                return
            times["open_decided"] = time.perf_counter()
            self.player.on_first_sample = lambda: times.setdefault("play", time.perf_counter())

        def confirm() -> str:
            """等確認講完。回傳 ok／cancel（作廢）／relang（估計語言錯咗，要用新語言重做）。"""
            nonlocal lang
            if not turn.wait_confirmed() and not turn.confirmed.is_set():
                return "cancel"
            times["confirmed"] = turn.confirmed_at
            self._carry = ""
            final_lang = self._choose_lang(detected, text)
            self.history.append(user_msg)
            self.emit({"type": "turn_user", "id": turn.id, "detected": detected, "text": text,
                       "reply_lang": final_lang, "speaker": speaker})
            self.emit(self.snapshot())
            if turn.cancel.is_set():
                return "cancel"
            self.player.on_first_sample = lambda: times.setdefault("play", time.perf_counter())
            if final_lang != lang:
                lang = final_lang
                spoken.clear()
                held.clear()
                return "relang"
            for audio in held:
                self.player.enqueue(audio)
            held.clear()
            if spoken:
                self.emit({"type": "turn_reply", "id": turn.id, "text": joined(), "done": False})
            return "ok"

        def joined() -> str:
            return (" " if lang == "en" else "").join(spoken)

        status = "ok" if "confirmed" in times else "pending"   # 公開問題路徑已經確認
        labels = [*self.profile.aliases(), "Someone"] if group else None
        while True:
            if "confirmed" in times:
                history = self.history[-history_len:]
            else:
                history = [*self.history[-(history_len - 1):], user_msg]
            persona = self.persona
            prompt = P.build_prompt(self.profile, persona, lang, group)
            for sentence in self.llm.stream_sentences(history, lang, turn.cancel, self.settings.max_sentences,
                                                      prompt, labels):
                times.setdefault("llm_first", time.perf_counter())
                audio = self.tts.synth(sentence, lang, persona.voice.instruct(), persona.voice.speed)
                times.setdefault("tts_first", time.perf_counter())
                if turn.cancel.is_set():
                    break
                if len(audio) == 0:
                    continue
                spoken.append(sentence)
                if status == "ok":
                    self.player.enqueue(audio)
                    self.emit({"type": "turn_reply", "id": turn.id, "text": joined(), "done": False})
                else:
                    held.append(audio)
                    if turn.confirmed.is_set():
                        status = confirm()
                        if status != "ok":
                            break
            if turn.cancel.is_set() or status == "cancel":
                break
            if status == "pending":
                status = confirm()
            if status != "relang":
                break
            status = "ok"   # 已確認，用新語言重做一次
        reply = joined()

        if "confirmed" not in times:
            return   # 提早開始作廢（對方仲講緊）：靜靜雞放棄
        if turn.cancel_reason == "continue" and "play" not in times and group:
            # 群組：AI 未出聲已經有人開口（多數係其他人接話）：放棄回覆，問題留喺對話做上下文，唔合併
            self.emit({"type": "turn_reply", "id": turn.id, "text": "", "done": True, "interrupted": "yield"})
            return
        if turn.cancel_reason == "continue" and "play" not in times:
            # 一對一：AI 未出聲對方就繼續講：撤回呢段，同下一段合併再答
            if self.history and self.history[-1] is user_msg:
                self.history.pop()
            self._carry = text
            self.emit({"type": "turn_reply", "id": turn.id, "text": "", "done": True, "interrupted": "continue"})
            return
        if reply:
            self.history.append({"role": "assistant", "content": reply + ("……" if turn.cancel.is_set() else "")})

        deadline = time.perf_counter() + 5
        while "play" not in times and time.perf_counter() < deadline and not turn.cancel.is_set() and reply:
            time.sleep(0.01)
        self.emit({"type": "turn_reply", "id": turn.id, "text": reply, "done": True,
                   "interrupted": turn.cancel_reason, "barge_ms": round(turn.barge_ms),
                   "latency": self._latency(turn)})

    def _latency(self, turn: Turn) -> dict:
        """各步驟時間（ms）。total 由對方停口計：確認時間減 end_ms。"""
        times, end_ms = turn.times, self.detector.cfg.end_ms
        latency = {"vad": round(end_ms)}
        prev = turn.started_at
        for key in ("asr", "open_decided", "llm_first", "tts_first"):
            if key in times:
                latency[key] = round((times[key] - prev) * 1000)
                prev = times[key]
        if "play" in times and "confirmed" in times:
            latency["play"] = round((times["play"] - max(prev, times["confirmed"])) * 1000)
            latency["total"] = round((times["play"] - times["confirmed"]) * 1000 + end_ms)
            saved = (times["confirmed"] - turn.started_at) * 1000
            if saved > 1:
                latency["saved"] = round(saved)
        return latency
