# 第 1、2 步測試記錄

更新日期：2026-10-09。

## 工具

- [tools/ProcLoopback](../tools/ProcLoopback/Program.cs)：C# 寫嘅 Windows application loopback 收音工具。可以指定 PID 或 process 名（例如 `--name Discord`，會自動搵 process tree 嘅根），包括或排除子 process，輸出 48 kHz／16-bit／stereo，寫入 WAV 或 raw stdout。
- [spike/capture_test.py](../spike/capture_test.py)：本 process 播 440 Hz，用 ProcLoopback 只收本 process，驗證收音。
- [spike/route_test.py](../spike/route_test.py)：播 chirp 入虛擬咪播放端，同時喺錄音端錄，量延遲、相關度同音量。

## 裝置方向（已查證）

| 用途 | WASAPI 裝置 |
| --- | --- |
| AI 播音（播放端） | MOTIV Mix Virtual Input (Shure Virtual Audio) |
| Discord 咪（錄音端） | MOTIV Mix Virtual Output (Shure Virtual Audio) |

Discord process tree：根 process `Discord.exe`，聲音由子 process `utility / audio.mojom.AudioService` 播出；以根 PID 加「包括 process tree」收音。

## 結果

| 測試 | 結果 | 備註 |
| --- | --- | --- |
| ProcLoopback 收指定 process | 通過 | 經 Steam Streaming Speakers 播 440 Hz，收到主頻 440 Hz；冇聲時都有連續數據 |
| 虛擬咪路由（MOTIV Mix 未開） | 失敗 | Virtual Output 完全無聲（-240 dBFS） |
| 虛擬咪路由（MOTIV Mix 已開） | 失敗 | MOTIV Mix 混音台冇加入任何輸入來源，Main 輸出無聲 |
| ProcLoopback 收 Discord（`--name Discord`） | 啟用成功 | 自動搵到根 PID；當時冇通話，收到 3 秒近乎無聲（-97 dBFS），未驗證真人聲音 |
| Steam Streaming Microphone 虛擬裝置對（後備候選） | 不適用 | 聲音傳到、延遲低，但音高變成約 0.46 倍：driver 將 48 kHz stereo 原始數據當 44.1 kHz mono 讀（0.46 ≈ 44.1／48／2）。要改 Windows 裝置預設格式先可能修正，唔建議用 |

MV7+ 直接錄音只有約 -91 dBFS，可能係靜音或增益問題，之後要確認。

### MOTIV Mix 路由（2026-10-09 後段）

- MOTIV Mix 更新到 1.10 後，混音台加入「MOTIV Mix Virtual」及「MV7+」兩條 channel。channel 底部 🎤 掣係**靜音**（唔係送去 Main）；🎧 係監聽。
- `route_test.py`：**通過**，相關度 0.964。
- `route_latency.py`（PortAudio 播放 DAC 同錄音 ADC 時間戳相減）：**路由延遲 310–345 ms**（5 次）。未用其他方法交叉驗證。
- MV7+ 喺 MOTIV Mix 靜音時，Virtual Output 係完全數碼靜音（-240 dBFS）。
- **MV7+ 未靜音、用戶冇講嘢時，Virtual Output 有約 950 Hz 持續音（連泛音），RMS -9 dBFS，另有約 -22 dBFS 直流偏移**；同時 Windows 直接收 MV7+ 係 -174 dBFS（完全靜）。即係支咪冇問題，問題喺 MOTIV Mix 讀 MV7+ 嘅路徑（懷疑格式或 driver 問題，未證實）。MOTIV Mix 電平表長期顯示約 -3 dBFS 係真實反映呢個訊號。錄音：`spike/out/idle_MOTIV_Output.wav`。
- 雜音波形係兩個電平（約 +0.26／-0.45）之間跳嘅方波。推算：細微底噪（約 2×10⁻⁹）嘅 32-bit 浮點數 bit 當整數讀，正數約 +0.38、負數約 -0.62，乘置中 pan -3 dB（×0.707）得 +0.27／-0.44，同實測吻合。即係 MOTIV Mix 將 MV7+ 浮點樣本當整數讀。
- 試過：Windows「預設格式」本身已係 1 聲道 24-bit 48 kHz（灰色不可改）；取消「Allow applications to take exclusive control」**冇改善**。
- **修正：MV7+ 錄音裝置內容 → 進階 → 取消「Enable audio enhancements」，重開 MOTIV Mix 後 Virtual Output 閒置降至 -103.5 dBFS**。音效增強處理似乎改變咗送俾 MOTIV Mix 嘅樣本格式（未完全證實）。
- 修正後再測：`route_test.py` 通過（相關度 0.969）；路由延遲 253–307 ms，冇變。

### 真人 Discord 測試

- 2026-10-09：用戶喺 Discord 語音房，咪設為 MOTIV Mix Virtual Output。用 [spike/say.py](../spike/say.py)（OmniVoice 合成）＋[spike/play.py](../spike/play.py) 播普通話「黃小旺你好，你聽到嗎？哈哈哈哈。」；**對方確認聽得清楚**。
- 用戶決定：暫時用 MOTIV Mix，VB-CABLE 遲啲先決定。
- [spike/discord_check.py](../spike/discord_check.py)：ProcLoopback `--name Discord` 收 15 秒對方真人語音（普通話），RMS -24.5 dBFS、峰值 -2.5 dBFS；Qwen3-ASR-1.7B 判斷 Chinese，辨識成連貫句子。**收對方語音通過**。按第一版政策，含真人聲音嘅測試錄音已刪除，文件不記錄對話內容。
- 未測：對方用喇叭時 AI 聲音回授。
- 用戶平時唔用 MOTIV Mix，單獨用 MV7+。MV7+ 嘅 DSP 設定（Auto-level、Denoiser）儲存喺支咪入面，改動會影響平時使用。
- 結論：MOTIV Mix 路由可用，但 300 ms 以上延遲會食咗 1.5 秒延遲目標約兩成，而且要長開 MOTIV Mix。後備 VB-CABLE 待用戶決定是否安裝後再量延遲比較。

## 第 2 步提早進行：ASR 初步結果

第 1 步等緊 MOTIV Mix 設定同真人測試期間，先做第 2 步嘅 ASR 部分。腳本：[spike/asr_bench.py](../spike/asr_bench.py)；樣本：[spike/samples.json](../spike/samples.json) 用 Windows 內置 SAPI 聲音（Tracy 粵、Hanhan 國、Haruka 日、Zira 英）合成，每語言 3 句。合成聲比真人清晰，結果只係初步，仍需真人錄音驗證。

| 模型 | VRAM | 準確度 | 語言判斷 | 每句延遲（4–6 秒話音） |
| --- | --- | --- | --- | --- |
| Qwen3-ASR-1.7B-hf | 3.9 GiB | 12 句基本全對，粵語口語字（唔、冇、哋、得唔得閒）正確 | 12／12，Cantonese／Chinese 分得開 | 410–640 ms |
| Qwen3-ASR-0.6B-hf | 1.5 GiB | 同樣基本全對，日文標點較少 | 12／12 | 380–690 ms |

- 輸出係簡體字，需要再轉繁體（例如 OpenCC）。
- 延遲高過估算（100–300 ms），而且 0.6B 冇快到：瓶頸唔係模型大細，而係 transformers 逐 token 生成嘅固定開銷，約 25 ms／token，每句約 19 tokens。
- `cache_implementation="static"` 反而慢四倍（約 110 ms／token）。
- `torch.compile` 需要 MSVC（`cl`），本機 PATH 未有，未能測試。
- 模型檔已放喺 `models/hf/hub/`，冇落 `~/.cache`。

### ASR 加速嘗試（未成功）

- 瓶頸係 transformers 每生成一個 token 都由 Python 逐個派細 GPU kernel，CPU 開銷大過 GPU 運算；0.6B 同 1.7B 每 token 都約 25 ms 就係證據。
- Static cache 單獨用（冇 compile）每步要計成段預留長度：一次 110 ms／token，接 MSVC 環境後 28 ms／token，冇改善。
- `torch.compile`：第一次因 PATH 冇 MSVC `cl` 失敗；用 `vcvars64.bat` 後，`reduce-overhead`（CUDA Graphs）模式出錯：「accessing tensor output of CUDAGraphs that has been overwritten」。Qwen3-ASR 音訊編碼器有 `.item()`（graph break），加上 generate 重用輸出，同 CUDA Graphs 唔兼容。
- 可再試：只 compile 文字解碼器並用唔包 CUDA Graphs 嘅模式；改用專門推理 runtime；或者靠「預先計算」將辨識時間同等候靜音重疊。

## 第 2 步：LLM 結果

腳本：[spike/llm_bench.py](../spike/llm_bench.py)。運行：llama.cpp `b11515` Windows CUDA 13.4 版（`tools/llama.cpp/`），`-ngl 99 -c 4096 -fa on`，關閉 thinking。模型：bartowski Q4_K_M GGUF，放喺 `models/gguf/`。對方話語用 12 句樣本原文（未經 ASR）。

| 模型 | VRAM | 第一 token 中位數／最差 | 第一段（可交 TTS）中位數／最差 | 全句中位數／最差 |
| --- | --- | --- | --- | --- |
| Qwen3.5-9B Q4_K_M | 5.6 GiB（實測） | 48／95 ms | 69／107 ms | 258／393 ms |
| Qwen3.5-4B Q4_K_M | 未量 | 41／69 ms | 65／77 ms | 171／276 ms |

- 延遲遠低於估算（150–300 ms）；llama.cpp 約 10 ms／token。
- 9B 廣東話地道（「係呀，我今晚有空，你喺邊度想食？」），口語字多、書面字近乎冇；4B 都講到口語，但較多前後矛盾同角色混亂（例如「我剛才講咗啲好快」）。**選 9B**，4B 只快約 10 ms。
- 第一次測試發現普通話回覆被帶成粵語：原因係 system prompt 用粵語寫。改為基本提示用英文、每種語言嘅規則用該語言寫，之後普通話回覆冇再出現粵語字。
- 偶爾回覆有換行（日文），交 TTS 前要清理。
- 部機 LM Studio 已有 `Qwen3.5-9B-Q4_K_M.gguf`，但按用戶要求模型要放喺專案 `models/`，所以另外下載。

## 第 2 步：TTS 結果（OmniVoice）

先測 OmniVoice，因為 CosyVoice3 官方鎖 `torch==2.3.1`（CUDA 12.1），唔支援 RTX 5070 Ti（Blackwell 需要 CUDA 12.8／torch 2.7 以上），而且日文要先轉片假名。OmniVoice 用現有 `..\OmniVoice\.venv`（同 Gaijincall 並排）（torch 2.8 cu128）運行，模型複製到 `models/OmniVoice/`（`~/.cache` 嗰份缺 `audio_tokenizer/preprocessor_config.json`，唔用）。

腳本：[spike/tts_omnivoice.py](../spike/tts_omnivoice.py)（合成 LLM 9B 嘅實際回覆）、[spike/tts_asr_check.py](../spike/tts_asr_check.py)（用 Qwen3-ASR-1.7B 反向辨識，檢查語言同錯誤率；中文按字、英文按詞，比較前統一簡體）。聲線：voice design `female, young adult`，語言代碼 yue／zh／ja／en，fp16。

| 設定 | 每句合成時間 | VRAM | 語言判斷正確 | 平均錯誤率 粵／國／日／英 |
| --- | --- | --- | --- | --- |
| num_step 16 | 中位數 374 ms，最差 443 ms | 2.0 GiB | 12／12 | 3%／1%／3%／0% |
| num_step 8 | 中位數 185 ms，最差 204 ms | 2.0 GiB | 11／12 | 5%／1%／2%／33%（en-3 合成失敗，ASR 冇辨識到任何字） |

- 合成時間同句子長短幾乎無關（4–7 秒音訊都約 360 ms，RTF 約 0.07），係 diffusion 步數嘅固定開銷。所以「第一段喺逗號就交 TTS」對 OmniVoice 冇好處；應該按句交，第一句越短越好。
- 廣東話用語言代碼 `yue` 已經被 ASR 判斷為 Cantonese，唔需要廣東話參考聲。
- 8 步唔穩定，維持 16 步。
- ASR 反向檢查只證明聽得明同語言啱，**唔代表自然**；需要人耳試聽。

## 實測延遲預算（未計 GPU 爭用）

| 步驟 | 估算 | 實測 |
| --- | --- | --- |
| VAD 等靜音 | 500–800 ms | 未測（可調） |
| ASR | 100–300 ms | 410–640 ms（1.7B，transformers） |
| LLM 到第一句完成 | 200–450 ms | 約 70–260 ms（第一段 69 ms，全句中位數 258 ms） |
| TTS 第一句 | 200–500 ms | 約 370 ms（OmniVoice 16 步） |
| 虛擬咪路由 | （包喺 Discord 傳送） | MOTIV Mix 310–345 ms |
| Discord 傳送 | 100–300 ms | 未測 |

模型部分（ASR＋LLM＋TTS）約 0.9–1.3 秒。配合「靜音 300 ms 開始預先計算、600 ms 確認先播」，預計感受到嘅延遲約 1.3–1.7 秒，貼近中位數 1.5 秒目標。最大改善空間係 ASR。

## 第 3 步：即時對話第一版（指令行）

程式：[app/console.py](../app/console.py)（控制台）＋[app/engine.py](../app/engine.py)，模組 `audio_io`（ProcLoopback 收 Discord、播去虛擬咪、可清空打斷）、`turns`（Silero VAD：開始 96 ms、講完 600 ms 靜音、最短 300 ms、打斷 300 ms、pre-roll 300 ms）、`asr`、`llm`（llama-server 串流，第一段喺逗號切、之後按句切）、`tts`＋`tts_worker`（OmniVoice 喺佢自己環境做 worker，stdin／stdout 傳 48 kHz float32）。唔保存錄音或逐字稿。

離線測試（`--test-wav` 用 7 段 SAPI 樣本扮對方，輸出播去 Steam Streaming Speakers，冇人聽到）：

- 四語言都有回應；打斷有效（AI 未講完，下一段樣本開始就停）。
- 對方停口 → AI 開始播：約 1.5–2.1 秒（未計虛擬咪約 300 ms 同 Discord 傳送）。分項：ASR 250–780 ms、LLM 第一段 90–260 ms、TTS 約 500 ms（比單獨測試 370 ms 慢，懷疑同 LLM 爭 GPU；第一輪 2 秒係預熱不足）。
- 修正：語言切換由「一律連續兩輪」改為「句子夠長（中日 ≥6 字、英文 ≥3 詞）即刻轉，短句先等兩輪」；英文多句之間補空格。
- SAPI 樣本句中停頓會被 600 ms 規則切成兩輪；真人要再觀察。
- 下一步改善延遲：預先計算（靜音 300 ms 開始 ASR／LLM）、ASR 加速、TTS 預熱同步數。

## 第 4 步：控制台（提早做）

- 開法：`start.cmd`（或 `uv run --extra asr python app/console.py`），瀏覽器開 `http://127.0.0.1:8765/`，只聽 127.0.0.1，檢查 Host header 防 DNS rebinding。
- 功能：啟用／停止 AI 模式、暫停／恢復（全域快捷鍵 Ctrl+Alt+P，用 RegisterHotKey）、回覆語言（自動／鎖定）、AI 聲音輸出裝置、**監聽**（「我都要聽到 AI 把聲」：開關、裝置〔預設 Windows 預設輸出〕、音量）、講完判斷靜音時間、即時狀態、今次對話同每輪延遲。設定存 `config/settings.json`；對話只喺網頁記憶體，唔儲存。
- 修正：
  - 喺背景 thread 開 WASAPI stream 會報誤導性嘅 WDM-KS「Unanticipated host error」：要先 `CoInitializeEx`（`audio_io.ensure_com`）。
  - 每種語言第一次用時 LLM＋TTS 特別慢（第一輪 5.4 秒），載入時四語言各預熱一次。
  - 之前強制停控制台會留低 llama-server 孤兒霸住 VRAM（曾經用到 15.7／16 GiB）：控制台啟動時將自己放入 Windows Job Object（KILL_ON_JOB_CLOSE），實測強制殺控制台後子 process 全部結束，VRAM 跌返基準 1.4 GiB。
  - TTS worker 單句失敗唔再成個死（回傳靜音，錯誤寫 `logs/tts_worker.log`）；冇可讀字嘅段落唔送合成。
- 測試模式（`--test-wav`）四語言對答、打斷、暫停／恢復都正常；預熱後非首輪延遲約 1.6–2.3 秒（未計虛擬咪同 Discord）。
- 全部載入後 GPU 用量約 13.9／16 GiB（包括系統約 1.4 GiB）。

## 真人試用回饋：講太長、成日被搶話（2026-10-09）

- 回覆長度：系統提示改為「最多 N 句」，各語言加每句長度限制（中 20 字、日 25 字、英 15 詞）；`max_tokens` 由 120 改為 40×N；程式講夠 N 句即刻停。控制台可揀 1–3 句，預設 2。
- 打斷分兩個階段：
  - AI 未出聲（ASR／LLM／TTS 中）對方再講 ≥300 ms：當對方未講完，撤回今次回覆，同下一段合併再答。
  - AI 講緊：對方要講夠 `barge_in_ms`（預設 700 ms，控制台 0.3–2 秒）先打斷；「嗯」「哦」、笑聲唔會打斷。
- 修 bug：之前取消開關喺 ASR 完先建立，ASR 期間對方開口嘅打斷會失效，AI 照答前半句同對方撞埋講。改為每輪自己嘅取消開關。
- 控制台顯示打斷原因（「對方未講完，已同下一句合併」／「被打斷（對方講咗 X 秒）」）。
- 測試模式：句中停 0.9 秒嘅樣本、普通話兩段、英文兩段都成功合併；回覆變為一兩句短句；延遲 1.3–1.8 秒。AI 講緊時被打斷嘅情況未喺真人測試驗證。
- 測試用 `--play-device` 臨時覆蓋唔再寫入 `config/settings.json`。

## 準確度同加速（2026-10-09 後段）

用戶回饋：對方講普通話、鎖定日文回覆會出錯；要求提高準確度同加速；介面用書面詞、英文為主。

**準確度**
- 重現（[spike/cross_lang_check.py](../spike/cross_lang_check.py)）：鎖定日文時 LLM 跟咗對方語言（普通話、廣東話、英文），再由 TTS 用日文讀中文句，讀錯（「有空」聽成「有課」）。原因：語言規則只喺系統提示末尾。
- 修正：每次送 LLM 時喺最後一句對方說話後加目標語言提示（例如「（必ず日本語で返事してください）」），唔入對話紀錄。之後鎖定日文、廣東話、普通話、英文，對方用其他三種語言都跟足鎖定語言。
- TTS 按句子實際文字揀語言（有假名用日文、純拉丁字母用英文），避免用錯語言讀。
- ASR 中文輸出由簡體轉繁體顯示（廣東話 `s2hk`、普通話 `s2tw`；`s2t` 會將「吃」轉成「喫」所以唔用）。

**加速**
- ASR 改用 llama.cpp（ggml-org `Qwen3-ASR-1.7B-Q8_0.gguf`＋`mmproj`，放 `models/gguf/asr/`）：12 句樣本輸出同 transformers 版一樣，每句由約 480 ms 降到中位數 104 ms、最差 128 ms（[spike/asr_llamacpp_bench.py](../spike/asr_llamacpp_bench.py)）；VRAM 約 2.4 GiB（原本 3.9 GiB）。
- TTS 由 16 步改 12 步：每句 374 → 273 ms，ASR 反向檢查四語言語言判斷全對、錯誤率不變；10 步 226 ms 亦可，但距離 8 步失敗太近，暫用 12。
- 提早開始：對方靜音達 `end_ms - 300 ms`（最少 200 ms）就開始 ASR／LLM／TTS，但等靜音達 `end_ms` 確認先顯示同播放；期間對方再講就作廢（VAD 累積成句，下次連前半句一齊辨識）。每輪慳約 320 ms。
- 結果（測試模式，end_ms 550）：**對方停口 → AI 開始播 0.71–0.93 秒**（之前 1.5–2.3 秒），未計虛擬咪約 300 ms 同 Discord 傳送。

**對話行為**
- AI 講緊嘢時對方開始講、但未夠打斷門檻（附和「嗯」「哦」、笑聲）：唔當新一輪，唔回應。
- 回覆播緊時被打斷：介面補報「Interrupted after X s」，對話紀錄標記未講完。
- 太短嘅聲音被丟棄時重設「對方講緊嘢」狀態（之前會卡住）。
- 測試：barge.wav（AI 講緊時對方插入長句）成功打斷；backchannel.wav（AI 講緊時「嗯」）冇觸發回應。

**介面**：改為英文為主、書面用詞；修正「Monitor AI voice」關閉時選項仍顯示（`[hidden]` 被 `display:grid` 蓋過）。

**其他**：llama-server（LLM、ASR）log 寫 `logs/llm.log`、`logs/asr.log`。全部載入後 GPU 約 12.8／16 GiB（包括系統）。

## 角色（性格）

用戶決定：AI 以**用戶本人**身份講嘢，但可以切換唔同性格；聲線先用 OmniVoice voice design。

- 個人資料（Profile：名、簡介、資料）所有性格共用，存 `config/profile.json`（唔入 git）。
- 性格（Personality：說話方式、口頭禪〔按語言〕、聲線〔性別、年齡、音高、耳語、語速 0.8–1.3〕）：預設 Natural、Cheerful、Calm、Playful 喺 [app/personas/](../app/personas/)；用戶修改存 `config/personas/<id>.json` 覆蓋預設，可以「Restore default」。模組：[app/personas.py](../app/personas.py)。
- 系統提示次序：角色提示（英文）→ 技術規則（長度、格式）→ 語言規則；技術規則喺後面，角色設定推翻唔到長度同語言要求。口頭禪只放當時回覆語言嗰組。
- 聲線值只接受 OmniVoice voice design 支援嘅選項（控制台用下拉選單），避免 instruct 錯誤令合成失敗。
- 切換性格或修改個人資料會清空對話紀錄（避免前一個性格嘅說話影響新性格）。
- 「Preview voice」只喺監聽裝置（或 Windows 預設輸出）播，唔送 Discord；用表格入面未儲存嘅聲線設定。
- 測試：四個性格載入正常；Cheerful 回覆明顯較興奮（「好呀！」「土曜は空いてるよ！」），四語言仍跟回覆語言；個人資料儲存／還原正常；非法 id（例如 `../evil`）被拒絕。
- 修正：語速加快時好短嘅句子（例如「對不起，」）OmniVoice 估計長度變 0 而失敗，改為失敗時用正常語速重試。

## 多人：講者辨識同群組模式

**講者聲紋模型比較**（[spike/speaker_bench.py](../spike/speaker_bench.py)；sherpa-onnx CPU 2 threads；Windows SAPI 5 把聲、每人 4 長句＋2 短句）

| 模型 | 每句 | 同一人最低／唔同人最高相似度 | 即時分組（門檻 0.5） |
| --- | --- | --- | --- |
| **3D-Speaker CAM++ zh_en advanced** | **18 ms** | 0.82／0.45 | **5 組全對** |
| 3D-Speaker ERes2NetV2 zh | 84 ms | 0.85／0.60 | 85% |
| WeSpeaker ResNet34 en | 33 ms | 0.79／0.68 | 45% |

選 CAM++（[app/speakers.py](../app/speakers.py)，模型放 `models/speaker/`）。SAPI 聲音差異大，真人同性別同語言會難好多，所以預設門檻 0.55，控制台可調，亦可以改名同合併講者。少過 1 秒嘅句子唔開新講者。聲紋只放記憶體，停 AI 模式即清除。

注意：`sherpa-onnx` 1.13.8 喺 uv 下冇自動裝 `sherpa-onnx-core`，會誤用 Windows 自帶嘅舊 `System32\onnxruntime.dll`（1.17，報「API version [28] is not available」）；要另外加 `sherpa-onnx-core==1.13.8`。

**群組模式**（控制台「Group chat」）
- 每句前面加講者名送 LLM（例如「Speaker 2: …」），系統提示講明係群組。
- 只喺叫你個名或者暱稱（「About you → Also called」）時回應；比較前統一簡體、細楷、去空格，「亞／阿」當同一字（ASR 會將「阿明」寫成「亞明」）。
- 選「Called by name, or an open question nobody answers」時：冇叫名嘅句子等 1.2 秒都冇人開口，再用 LLM 判斷（yes／no）係咪公開問題、適合你答。
- 冇回應嘅句子都記入對話做上下文（群組保留 20 句）。
- AI 準備回覆期間有人開口：群組模式放棄回覆（「Someone else spoke」），**唔合併**（一對一先合併；之前會將 David 嘅問題併入 Zira 嗰句兼標錯講者）。
- 模型喺回覆開頭加「名字:」會自動刪走。
- 測試（[spike/out/group](../spike/out/group)，SAPI 三把聲；Ming／阿明）：講者 3 人全對；公開問題有人答 → 放棄；冇叫名 → 只聽；叫名（英文、「亞明」）→ 即時回應；冇人答嘅公開問題 → 等約 1.6 秒後回應。

## 串流 ASR（llama.cpp，LocalAgreement-2）

Qwen3-ASR 官方串流只支援 vLLM（Linux），所以喺 llama.cpp 上面自己做：[app/streaming_asr.py](../app/streaming_asr.py)。每多 0.5 秒聲就重新辨識成段，連續兩次開頭一致嘅部分當已確定；已確定嘅字用 assistant prefill（`language X<asr_text>已確定文字`）填返，模型只生成後面。模組唔依賴 engine，其他項目可以直接用。

實時模擬（[spike/streaming_asr_bench.py](../spike/streaming_asr_bench.py)；12 句 SAPI 樣本＋每語言 3 句接埋嘅長段 13–17 秒；1.7B Q8_0；未同 LLM／TTS 同時運行）：

| | prefill | 冇 prefill |
| --- | --- | --- |
| 第一次出字 | 0.53 秒（= 等夠 0.5 秒聲＋辨識） | 0.52 秒 |
| 每次辨識（短句／長段中位） | 60／82 ms | 69／129 ms |
| 講完時已確定（短句中位） | 100% | 94% |
| 講完時顯示同最終文字差別 | 0.4% | 0.4% |
| 最後一次：填返已確定字 | **39／65 ms**（短／長），CER 2.4%（初版量到 16 ms 有偏差，見下） | 未重量，CER 2.0% |
| 最後一次：成段重做 | 約 100 ms（獨立量），CER 2.0% | 同左 |

- 講完嗰刻，畫面已經顯示到差唔多全句；CER 主要係「呀／啊」、「吓／下」呢類同音字，唔算真錯。
- 填返已確定字快好多，但已確定嘅錯改唔返（ja-2「言っていいただけ」多咗一個「い」，CER 4.3%）；成段重做最準，標點都較自然。
- 初版「填返 16 ms」係喺成段重做之後先量，llama-server 已經 cache 咗同一段聲嘅 prompt，所以偏快；改為先量填返（同 engine 次序一樣）係 39／65 ms。
- 試過填返時留最尾 2 個字畀模型重寫（想修正上面重複「い」）：反而變「言っいただけ」漏字，CER 2.8%、64 ms，所以唔留。
- GPU 用量：每 0.5 秒約 60–80 ms，即約 15%。長段每次辨識會隨長度增加（17 秒段最差 378 ms），長會議要按停頓切段。
- 未測：真人錄音、雜音、同 LLM／TTS 爭 GPU。
- 之後改咗「兩個都係標點就當一致」（SenseVoice 每次標點都唔同）；重測 Qwen 每次辨識 44／63 ms，其他不變。

**接入 Gaijincall**（Qwen only）：
- VAD 新增 on_audio，對方講緊嘢期間每塊聲交 StreamingASR；每句開始 eset()，暫停／停止後要等下一句開始先再串流。
- 提早開始／確認講完時用 stream.transcribe(turn.audio, turn.segment)：同一段就填返已確定嘅字。
- 控制台「Conversation」上面新增「Hearing」即時字幕：黑字已確定、灰字臨時；記入對話後自動收起。
- 測試模式（yue-1、cmn-1、ja-2、en-2、pause-merge、backchannel）：每 0.5 秒更新一次字幕；ASR 一步 31–84 ms（之前約 100 ms）；**對方停口 → AI 開始播 0.70–0.87 秒**（之前 0.71–0.93 秒）。因為提早開始已經遮咗大部分 ASR 時間，總延遲只快約 40 ms。

**SenseVoice-Small 比較**（[app/sensevoice.py](../app/sensevoice.py)，sherpa-onnx CPU int8，模型放 `models/sensevoice/`；[spike/sensevoice_bench.py](../spike/sensevoice_bench.py)）

離線（每句一次；短句 12 句／長段 4 段；CER 平均）：

| 條件 | Qwen3-ASR-1.7B（GPU） | SenseVoice 2024-07-17（CPU 4 threads） |
| --- | --- | --- |
| 速度（短句／長段中位） | 78／194 ms | **56／179 ms**（2 threads：86／291 ms） |
| 記憶體 | VRAM 約 2.4 GiB | **RAM 約 270 MB，VRAM 0** |
| 乾淨 | 2.0%／1.9% | 2.0%／2.2% |
| 白噪音 10 dB | 3.4%／2.7% | 3.2%／2.6% |
| 白噪音 0 dB | **5.5%／5.8%** | 8.9%／6.7% |
| 背景人聲 10 dB | 2.4%／1.9% | 2.0%／4.2% |
| 背景人聲 5 dB | 18.5%／**3.2%** | **4.7%**／14.7% |

- 乾淨樣本兩個都差唔多全對（粵語 8% 主要係「呀／啊」同音字），SAPI 聲太易，分唔到高低。
- 大雜音下各有弱點：Qwen 喺背景人聲 5 dB 時有 2 句日文**跟咗背景嗰把廣東話聲**（成句譯錯人）；SenseVoice 會漏字（英文長段漏一半），但唔會跟錯人。
- `2025-09-09` 版（ASLP-lab 粵語微調）唔啱用：普通話、日文、英文都判斷成粵語，日文差唔多全錯（CER 82%），英文全大楷冇標點。
- SenseVoice 日文會喺詞之間加空格，轉接層已刪。

串流兩段式（SenseVoice CPU 出臨時字、Qwen3-ASR 出最終；step 0.5 秒）：

| | 單一 Qwen（prefill） | SenseVoice＋Qwen |
| --- | --- | --- |
| 第一次出字 | 0.51 秒 | 0.50 秒 |
| 每次臨時辨識（短／長） | 44／63 ms（GPU） | 36／93 ms（CPU） |
| 講完時已確定（短／長） | 100%／100% | 94%／65% |
| 講完到最終文字（短／長） | 填返 39／65 ms；重做 113／238 ms | 重做 130／436 ms |

- Gaijincall 用單一 Qwen 較好：已確定比例高、可以填返，最後一步最快；SenseVoice 慳嘅只係 GPU 時間。
- 會議 app：如果要慳 VRAM 或者部機冇強 GPU，SenseVoice 單獨用已經夠（準確度喺乾淨同中等雜音下同 Qwen 相若，只用 CPU）；要最準就講完一段再交 Qwen。

## VRAM 小計（實測）

ASR 1.7B 3.9 GiB ＋ LLM 9B 5.6 GiB ＋ TTS 2.0 GiB ＝ 11.5 GiB；加系統已用約 1.8 GiB，約 13.3／16 GiB。三個同時運行時嘅 GPU 爭用未測。

## 待處理

1. 喺 MOTIV Mix 混音台加入「MOTIV Mix Virtual」及「Shure MV7+」兩個輸入來源，再跑 `route_test.py`。
2. 通過後，請一位朋友喺 Discord 驗證音質、降噪及聲音觸發收音嘅影響，並測試對方用喇叭。
3. 用 ProcLoopback `--name Discord` 實際收朋友把聲，確認冇混入其他程式聲音。
