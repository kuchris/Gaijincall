"""將所有模型 cache 指向專案 models/ 資料夾。必須喺 import transformers／huggingface_hub 之前 import。"""

import os
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

os.environ["HF_HOME"] = str(MODELS_DIR / "hf")
os.environ["HF_HUB_CACHE"] = str(MODELS_DIR / "hf" / "hub")
os.environ["MODELSCOPE_CACHE"] = str(MODELS_DIR / "modelscope")
os.environ["TORCH_HOME"] = str(MODELS_DIR / "torch")
os.environ["OLLAMA_MODELS"] = str(MODELS_DIR / "ollama")
