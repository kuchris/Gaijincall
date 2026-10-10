# Gaijincall

A local, multilingual voice assistant that talks in your own Discord voice channel. It listens to the other participants, then replies by voice in Cantonese, Mandarin, Japanese or English. Speech recognition, the language model and speech synthesis all run on your own GPU. No cloud AI service is used.

> Status: personal prototype. It runs on Windows with an NVIDIA GPU and has only been tested on one machine (RTX 5070 Ti, 16 GB).

## How it works

```
Discord audio ──► ProcLoopback (capture Discord only)
                    │
                    ▼
                 Silero VAD ──► Qwen3-ASR 1.7B (llama.cpp, streaming)
                                      │
                                      ▼
                                 Qwen3.5-9B (llama.cpp) ──► OmniVoice TTS
                                                                 │
Discord microphone ◄── virtual audio cable ◄─────────────────────┘
```

- **Capture**: `tools/ProcLoopback` uses Windows process loopback to record audio from the Discord process tree only.
- **Turn-taking**: Silero VAD decides when the other person has finished. The reply is prepared speculatively during short pauses, and the other person can interrupt the AI.
- **ASR**: [Qwen3-ASR-1.7B](https://github.com/QwenLM/Qwen3-ASR) on llama.cpp. The utterance is re-transcribed every 0.5 s with LocalAgreement, so a live transcript appears in the console while the person is speaking.
- **LLM**: Qwen3.5-9B (Q4_K_M) on llama.cpp. Thinking is disabled and the reply is streamed sentence by sentence.
- **TTS**: [OmniVoice](https://github.com/k2-fsa/OmniVoice), using a designed voice. It runs as a worker process in OmniVoice's own Python environment.
- **Group mode** (optional): 3D-Speaker CAM++ speaker embeddings label who is speaking. The AI replies only when you are addressed by name, or optionally to an open question nobody answers.
- **Console**: a local web page at `http://127.0.0.1:8765/` for start, pause (`Ctrl+Alt+P`), settings, personas, speakers and a conversation log with per-turn latency.

Measured in test mode: about **0.7–0.9 s** from the end of the other person's speech to the start of the AI's voice. This excludes the virtual audio cable and Discord transport, which add roughly 0.3 s or more. Fully loaded, it uses about 13 GB of VRAM. Details are in [docs/spike-1-audio.md](docs/spike-1-audio.md) (Cantonese).

## Requirements

- Windows 11, or Windows 10 build 20348 or later (needed for process loopback capture)
- NVIDIA GPU with about 16 GB VRAM and a CUDA 12.8+ capable driver
- [uv](https://docs.astral.sh/uv/), [.NET 9 SDK](https://dotnet.microsoft.com/download), Git
- A virtual audio device for the AI's voice. The author uses MOTIV Mix; VB-CABLE or similar should also work but has not been tested.

## Setup

All model files live under `models/`, which is not tracked by git.

### 1. Python environment

```bash
uv sync --extra asr
```

### 2. llama.cpp

Download a recent Windows CUDA build from the [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases): `llama-*-bin-win-cuda-*-x64.zip` plus the matching `cudart-*.zip`. Extract both so that `tools/llama.cpp/bin/llama-server.exe` exists. The build must support Qwen3-ASR audio input.

### 3. ProcLoopback

```bash
dotnet build tools/ProcLoopback -c Release
```

### 4. OmniVoice

Clone OmniVoice **next to** this repository and create its virtual environment as described in its README:

```
git/
├── Gaijincall/
└── OmniVoice/        ← https://github.com/k2-fsa/OmniVoice, with .venv inside
```

If it is somewhere else, set the `OMNIVOICE_PYTHON` environment variable to its `python.exe`.

### 5. Models

```bash
uv run --extra asr python -c "from huggingface_hub import hf_hub_download as d; d('bartowski/Qwen_Qwen3.5-9B-GGUF', 'Qwen_Qwen3.5-9B-Q4_K_M.gguf', local_dir='models/gguf'); [d('ggml-org/Qwen3-ASR-1.7B-GGUF', f, local_dir='models/gguf/asr') for f in ('Qwen3-ASR-1.7B-Q8_0.gguf', 'mmproj-Qwen3-ASR-1.7B-Q8_0.gguf')]"
uv run --extra asr python -c "from huggingface_hub import snapshot_download; snapshot_download('k2-fsa/OmniVoice', local_dir='models/OmniVoice')"
curl -L -o models/speaker/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx --create-dirs https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx
```

The resulting layout:

| File | Used for |
| --- | --- |
| `models/gguf/Qwen_Qwen3.5-9B-Q4_K_M.gguf` | LLM |
| `models/gguf/asr/Qwen3-ASR-1.7B-Q8_0.gguf`, `mmproj-Qwen3-ASR-1.7B-Q8_0.gguf` | ASR |
| `models/OmniVoice/` | TTS |
| `models/speaker/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx` | Group mode speaker labels |

Silero VAD comes with the `silero-vad` Python package.

### 6. Audio routing

1. In the console, set **AI voice output** to the playback side of your virtual device (for example "MOTIV Mix Virtual Input").
2. In Discord, set **Input Device** to the recording side of the same device (for example "MOTIV Mix Virtual Output").
3. Optionally turn on **Monitor** in the console to hear the AI yourself.

## Run

```bash
start.cmd
```

The console opens in your browser and loads the models, which takes about a minute. Join a voice channel in Discord, then press **Start AI mode**.

To test offline without Discord, play WAV files as the other person:

```bash
uv run --extra asr python app/console.py --test-wav a.wav b.wav --play-device "Speakers"
```

## Repository layout

| Path | Contents |
| --- | --- |
| `app/` | The assistant: engine, ASR/LLM/TTS wrappers, VAD, streaming ASR, personas, speaker tracking, web console |
| `tools/ProcLoopback/` | C# process loopback capture |
| `spike/` | Benchmarks and experiments behind the design choices |
| `docs/` | Design notes, milestone plan and test log (Cantonese) |

## Responsible use

This tool replies in your voice channel using a synthetic voice. Make sure the people you talk with are comfortable with that. Follow Discord's Terms of Service and your local laws on recording and automated conversation.

## License

[MIT](LICENSE)
