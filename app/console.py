"""本機繁中網頁控制台。只聽 127.0.0.1。

用法：uv run --extra asr python app/console.py [--port 8765] [--no-browser] [--test-wav a.wav b.wav]
"""

import paths  # noqa: F401  # 必須最先 import

import argparse
import json
import queue
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import hotkey
import jobobject
from audio_io import default_output_name, output_device_names
from engine import Engine

STATIC = Path(__file__).resolve().parent / "static"
HOTKEY_LABEL = "Ctrl+Alt+P"
ALLOWED_HOSTS: set[str] = set()

engine = Engine()
test_wavs: list[str] = []
hotkey_ok = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _host_ok(self) -> bool:
        # 防 DNS rebinding：只接受本機 Host
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            self.send_error(403)
            return False
        return True

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._host_ok():
            return
        if self.path in ("/", "/index.html"):
            body = (STATIC / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/devices":
            self._json({"outputs": output_device_names(), "default_output": default_output_name(),
                        "hotkey": HOTKEY_LABEL, "hotkey_ok": hotkey_ok})
        elif self.path == "/api/personas":
            self._json(engine.personas_info())
        elif self.path == "/api/speakers":
            self._json(engine.speakers_info())
        elif self.path == "/events":
            self._events()
        else:
            self.send_error(404)

    def do_POST(self):
        if not self._host_ok():
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json({"error": "JSON 格式錯誤"}, 400)
        if self.path == "/api/enable":
            engine.enable(test_wavs or None)
        elif self.path == "/api/disable":
            engine.disable()
        elif self.path == "/api/pause":
            engine.set_paused(bool(data.get("paused", not engine.paused)))
        elif self.path == "/api/settings":
            engine.update_settings(data)
        elif self.path in ("/api/persona", "/api/persona/reset", "/api/profile", "/api/preview"):
            try:
                if self.path == "/api/persona":
                    engine.save_persona(data)
                elif self.path == "/api/persona/reset":
                    engine.reset_persona(str(data.get("id", "")))
                elif self.path == "/api/profile":
                    engine.save_profile(data)
                else:
                    engine.preview_voice(str(data.get("persona", "")), str(data.get("lang", "")), data.get("voice"))
            except (ValueError, TypeError, KeyError) as e:
                return self._json({"error": str(e)}, 400)
            return self._json(engine.personas_info())
        elif self.path in ("/api/speaker/rename", "/api/speaker/merge", "/api/speakers/reset"):
            if engine.state == "loading":
                return self._json({"error": "Still loading"}, 409)
            try:
                if self.path == "/api/speaker/rename":
                    engine.rename_speaker(int(data["id"]), str(data.get("name", "")))
                elif self.path == "/api/speaker/merge":
                    engine.merge_speakers(int(data["keep"]), int(data["drop"]))
                else:
                    engine.reset_speakers()
            except (ValueError, TypeError, KeyError) as e:
                return self._json({"error": str(e)}, 400)
            return self._json(engine.speakers_info())
        else:
            return self.send_error(404)
        self._json(engine.snapshot())

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = engine.subscribe()
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except OSError:
            pass
        finally:
            engine.unsubscribe(q)


def main():
    global test_wavs, hotkey_ok
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--test-wav", nargs="*", default=[], help="測試模式：用呢啲 WAV 扮對方，唔收 Discord")
    parser.add_argument("--play-device", help="今次運行改用呢個輸出裝置並關閉監聽（唔寫入設定檔，測試用）")
    parser.add_argument("--monitor-device", help="今次運行嘅監聽／試聽裝置（唔寫入設定檔，測試用）")
    args = parser.parse_args()
    test_wavs = args.test_wav
    if args.play_device:
        engine.override_settings(play_device=args.play_device, monitor_on=False)
    if args.monitor_device:
        engine.override_settings(monitor_device=args.monitor_device)
    if not jobobject.kill_children_on_exit():
        print("⚠ 未能設定 Job Object：控制台被強制關閉時，子 process 可能殘留霸住 VRAM", flush=True)
    ALLOWED_HOSTS.update({f"127.0.0.1:{args.port}", f"localhost:{args.port}"})

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    print(f"控制台：{url}", flush=True)

    hotkey_ok = hotkey.register(hotkey.MOD_CONTROL | hotkey.MOD_ALT, ord("P"),
                                lambda: engine.set_paused(not engine.paused)).ok
    if not hotkey_ok:
        print(f"⚠ 快捷鍵 {HOTKEY_LABEL} 註冊失敗（可能被其他程式佔用）", flush=True)

    threading.Thread(target=engine.load, daemon=True).start()
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.close()


if __name__ == "__main__":
    main()
