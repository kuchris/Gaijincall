"""專案路徑同模型 cache 設定。必須喺 import transformers／huggingface_hub 之前 import。"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
PROC_LOOPBACK = ROOT / "tools" / "ProcLoopback" / "bin" / "Release" / "net9.0-windows" / "ProcLoopback.exe"
LLAMA_SERVER = ROOT / "tools" / "llama.cpp" / "bin" / "llama-server.exe"
LLM_MODEL = MODELS_DIR / "gguf" / "Qwen_Qwen3.5-9B-Q4_K_M.gguf"
OMNIVOICE_MODEL = MODELS_DIR / "OmniVoice"
# OmniVoice 喺佢自己嘅 venv 運行（預設同 Gaijincall 並排嘅 OmniVoice repo）；可用環境變數 OMNIVOICE_PYTHON 改
OMNIVOICE_PYTHON = Path(os.environ.get("OMNIVOICE_PYTHON",
                                       ROOT.parent / "OmniVoice" / ".venv" / "Scripts" / "python.exe"))

# 所有模型檔都要放喺專案 models/ 入面
os.environ["HF_HOME"] = str(MODELS_DIR / "hf")
os.environ["HF_HUB_CACHE"] = str(MODELS_DIR / "hf" / "hub")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TORCH_HOME"] = str(MODELS_DIR / "torch")
