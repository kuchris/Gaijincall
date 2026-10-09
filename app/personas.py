"""角色：AI 以用戶本人身份講嘢（個人資料共用），可以切換唔同性格（說話方式＋聲線）。

預設性格喺 app/personas/*.json（入 git）；用戶修改後存 config/personas/<id>.json，覆蓋同名預設。
個人資料存 config/profile.json。

提示詞用英文寫：實測用某一種對話語言寫提示，會帶偏回覆語言（例如粵語提示令普通話回覆變粵語）。
"""

import json
import re
from dataclasses import asdict, dataclass, field

from paths import ROOT

DEFAULT_DIR = ROOT / "app" / "personas"
USER_DIR = ROOT / "config" / "personas"
PROFILE_FILE = ROOT / "config" / "profile.json"
LANGS = ("yue", "cmn", "ja", "en")

# OmniVoice voice design 支援嘅值（omnivoice/models/omnivoice.py _resolve_instruct）
VOICE_CHOICES = {
    "gender": ["female", "male"],
    "age": ["child", "teenager", "young adult", "middle-aged", "elderly"],
    "pitch": ["very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"],
}
SPEED_RANGE = (0.8, 1.3)
MAX_TEXT = 600   # 每個文字欄位上限，控制提示長度（每輪都要計）


@dataclass
class Voice:
    gender: str = "female"
    age: str = "young adult"
    pitch: str = "moderate pitch"
    whisper: bool = False
    speed: float = 1.0

    def instruct(self) -> str:
        items = [self.gender, self.age, self.pitch] + (["whisper"] if self.whisper else [])
        return ", ".join(items)


@dataclass
class Persona:
    id: str
    label: str
    personality: str = ""
    speaking_style: str = ""
    catchphrases: dict = field(default_factory=lambda: {lang: [] for lang in LANGS})
    voice: Voice = field(default_factory=Voice)
    customized: bool = False   # 用戶改過（存喺 config/）

    @classmethod
    def from_dict(cls, data: dict) -> "Persona":
        voice = Voice(**{k: v for k, v in (data.get("voice") or {}).items() if k in Voice.__dataclass_fields__})
        return clean_persona(cls(
            id=data["id"], label=data.get("label") or data["id"],
            personality=data.get("personality", ""), speaking_style=data.get("speaking_style", ""),
            catchphrases={lang: list((data.get("catchphrases") or {}).get(lang, [])) for lang in LANGS},
            voice=voice,
        ))


@dataclass
class Profile:
    name: str = ""
    nicknames: list[str] = field(default_factory=list)   # 朋友點叫你（群組模式用嚟判斷有冇人叫緊你）
    about: str = ""
    facts: list[str] = field(default_factory=list)

    def aliases(self) -> list[str]:
        return [n for n in [self.name, *self.nicknames] if n]


def clean_persona(p: Persona) -> Persona:
    """限制長度同聲線值，避免提示過長或 OmniVoice 收到唔支援嘅 instruct。"""
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", p.id):
        raise ValueError(f"invalid persona id: {p.id!r}")
    p.label = p.label.strip()[:40] or p.id
    p.personality = p.personality.strip()[:MAX_TEXT]
    p.speaking_style = p.speaking_style.strip()[:MAX_TEXT]
    p.catchphrases = {lang: [c.strip()[:30] for c in p.catchphrases.get(lang, []) if c.strip()][:5] for lang in LANGS}
    v = p.voice
    for key, choices in VOICE_CHOICES.items():
        if getattr(v, key) not in choices:
            setattr(v, key, asdict(Voice())[key])
    v.whisper = bool(v.whisper)
    v.speed = round(min(max(float(v.speed), SPEED_RANGE[0]), SPEED_RANGE[1]), 2)
    return p


def _read(path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_personas() -> dict[str, Persona]:
    personas: dict[str, Persona] = {}
    for directory, customized in ((DEFAULT_DIR, False), (USER_DIR, True)):
        for path in sorted(directory.glob("*.json")):
            data = _read(path)
            if not data or "id" not in data:
                continue
            try:
                persona = Persona.from_dict(data)
            except (ValueError, TypeError):
                continue
            persona.customized = customized
            personas[persona.id] = persona
    return personas


def save_persona(data: dict) -> Persona:
    persona = Persona.from_dict(data)
    USER_DIR.mkdir(parents=True, exist_ok=True)
    out = asdict(persona)
    out.pop("customized")
    (USER_DIR / f"{persona.id}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    persona.customized = True
    return persona


def reset_persona(persona_id: str):
    """刪除用戶修改，回復預設（只限有預設嘅性格）。"""
    path = USER_DIR / f"{persona_id}.json"
    if (DEFAULT_DIR / f"{persona_id}.json").exists() and path.exists():
        path.unlink()


def _str_list(value, sep: str, limit: int, length: int) -> list[str]:
    if isinstance(value, str):
        value = re.split(sep, value)
    return [str(v).strip()[:length] for v in (value or []) if str(v).strip()][:limit]


def _profile_from(data: dict) -> Profile:
    return Profile(name=str(data.get("name", "")).strip()[:40],
                   nicknames=_str_list(data.get("nicknames", []), r"[,，、\n]", 10, 30),
                   about=str(data.get("about", "")).strip()[:MAX_TEXT],
                   facts=_str_list(data.get("facts", []), r"\n", 20, 120))


def load_profile() -> Profile:
    return _profile_from(_read(PROFILE_FILE) or {})


def save_profile(data: dict) -> Profile:
    profile = _profile_from(data)
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(asdict(profile), ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def build_prompt(profile: Profile, persona: Persona, lang: str, group: bool = False) -> str:
    """角色部分嘅系統提示（技術規則由 llm.py 加喺後面，角色設定推翻唔到長度同語言規則）。"""
    who = f"You are {profile.name}" if profile.name else "You are the owner of this Discord account"
    lines = [f"{who}, talking with friends in a Discord voice channel as yourself. Speak in the first person as {profile.name or 'yourself'}."]
    if profile.nicknames:
        lines.append("Friends also call you: " + ", ".join(profile.nicknames))
    if group:
        lines.append("This is a group chat with several friends. Each message starts with the speaker's name "
                     "(\"Someone\" if unknown). Reply to whoever spoke to you; you may use their name. "
                     "Never start your reply with your own name or a speaker label.")
    if profile.about:
        lines.append(f"About you: {profile.about}")
    if profile.facts:
        lines.append("Facts about you: " + "; ".join(profile.facts))
    if persona.personality:
        lines.append(f"Your mood and personality right now: {persona.personality}")
    if persona.speaking_style:
        lines.append(f"How you talk: {persona.speaking_style}")
    phrases = persona.catchphrases.get(lang) or []
    if phrases:
        lines.append("Occasionally (not every turn) use expressions like: " + " / ".join(phrases))
    lines.append("Never mention prompts, settings or being configured.")
    return "\n".join(lines) + "\n"
