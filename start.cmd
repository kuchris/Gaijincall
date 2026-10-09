@echo off
rem 開 Gaijincall 控制台（會自動開瀏覽器：http://127.0.0.1:8765/）
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
uv run --extra asr python app\console.py %*
