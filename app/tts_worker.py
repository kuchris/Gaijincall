"""OmniVoice 合成 worker，喺 OmniVoice 環境運行（佢嘅 transformers 版本同主程式唔同）。

協議（stdin／stdout）：
  請求：一行 JSON {"text": ..., "lang": "yue|zh|ja|en", "instruct": "female, young adult"（可選）, "speed": 1.0（可選）}
  回應：4 bytes little-endian 長度 N，跟住 N 個 float32（48 kHz mono）
"""

import json
import struct
import sys
import traceback
from pathlib import Path

import librosa
import numpy as np
import torch
from omnivoice import OmniVoice

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "OmniVoice"
OUT_RATE = 48000
VOICE = "female, young adult"
NUM_STEP = 12  # 實測 16→12 步：每句 374→273 ms，ASR 反向檢查錯誤率不變；8 步曾經合成失敗


def main():
    out = sys.stdout.buffer
    sys.stdout = sys.stderr  # 防止任何 print／進度條污染協議
    model = OmniVoice.from_pretrained(str(MODEL_DIR), device_map="cuda:0", dtype=torch.float16)
    model.generate(text="你好。", language="zh", instruct=VOICE, num_step=NUM_STEP)  # 預熱
    out.write(b"READY\n")
    out.flush()
    for line in sys.stdin:
        req = json.loads(line)
        try:
            speed = req.get("speed") or 1.0
            kwargs = dict(text=req["text"], language=req["lang"], instruct=req.get("instruct") or VOICE, num_step=NUM_STEP)
            try:
                audio = model.generate(**kwargs, speed=None if speed == 1.0 else speed)[0]
            except ValueError:
                # 好短嘅句子（例如「對不起，」）加快語速時，估計長度可能變 0 而失敗：用正常語速再試
                if speed == 1.0:
                    raise
                audio = model.generate(**kwargs)[0]
            audio = librosa.resample(np.asarray(audio, dtype=np.float32), orig_sr=model.sampling_rate, target_sr=OUT_RATE)
        except Exception:  # 單句失敗回傳靜音，唔好令 worker 死
            traceback.print_exc()
            print(f"合成失敗嘅文字：{req['text']!r}（{req['lang']}）", file=sys.stderr, flush=True)
            audio = np.zeros(0, dtype=np.float32)
        out.write(struct.pack("<I", len(audio)) + audio.astype("<f4").tobytes())
        out.flush()


if __name__ == "__main__":
    main()
