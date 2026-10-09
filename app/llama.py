"""啟動 llama.cpp llama-server 子 process 並等到就緒。"""

import subprocess
import time
import urllib.request
from pathlib import Path

from paths import LLAMA_SERVER, ROOT

LOG_DIR = ROOT / "logs"


def start_server(name: str, port: int, args: list[str], timeout_s: float = 180) -> subprocess.Popen:
    LOG_DIR.mkdir(exist_ok=True)
    log = open(LOG_DIR / f"{name}.log", "wb")
    proc = subprocess.Popen([str(LLAMA_SERVER), "--port", str(port), "--no-webui", *args],
                            stdout=subprocess.DEVNULL, stderr=log)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{name} llama-server exited; see {LOG_DIR / f'{name}.log'}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return proc
        except OSError:
            time.sleep(0.3)
    proc.kill()
    raise TimeoutError(f"{name} llama-server not ready within {timeout_s:.0f} s")


def model_path(*parts: str) -> str:
    return str(Path(ROOT, "models", *parts))
