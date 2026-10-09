"""下載 LLM GGUF 檔到 models/gguf/（支援斷點續傳）。

用法：uv run python spike/fetch_gguf.py
"""

import models_env  # noqa: F401  # 必須最先 import

from huggingface_hub import hf_hub_download

from models_env import MODELS_DIR

FILES = [
    ("bartowski/Qwen_Qwen3.5-9B-GGUF", "Qwen_Qwen3.5-9B-Q4_K_M.gguf"),
    ("bartowski/Qwen_Qwen3.5-4B-GGUF", "Qwen_Qwen3.5-4B-Q4_K_M.gguf"),
]

for repo, name in FILES:
    path = hf_hub_download(repo, name, local_dir=MODELS_DIR / "gguf")
    print(f"完成：{path}")
