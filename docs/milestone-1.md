# 第一版：自己 Discord 帳號嘅本機多語即時對話

更新日期：2026-10-09。狀態：修訂範圍已整理，待用戶確認完整第一版。

## 目標

用戶自己登入正常 Discord 客戶端，手動進入 server 嘅語音房。手動開啟本機 AI 模式後，AI 聽到對方說話就進行自然語音對話；支援廣東話、普通話、日文及英文。

第一版先一對一驗收，不使用雲端 AI API，不需要 OpenAI API key。Discord 只做語音對話，本機繁中控制台負責啟用、停止、語言及音訊設定。

## 使用流程

1. 用戶自己登入 Discord，進入想對話嘅語音房。
2. 喺本機控制台選好收音來源及輸出裝置，開啟 AI 模式。
3. AI 自動聆聽及回覆，跟對方嘅廣東話／普通話／日文／英文切換；亦可手動鎖定回覆語言。
4. 用戶可以用快捷鍵暫停 AI，自己接話；之後恢復或完全停止。
5. 對方喺 AI 播音時講嘢，可以打斷未播完嘅回覆。

本機會話不設固定時間上限。第一版不保存會話錄音或逐字稿，亦不生成分析報告；短期對話上下文供本次即時對答使用。

## 音訊接駁

預計流程：

Discord 播出對方聲音 → Windows 收音 → 本機語音辨識 → 本機對話模型 → 本機語音合成 → 虛擬咪 → 對方喺 Discord 聽到 AI 回覆。

- 優先評估 Windows application loopback，只收指定 Discord process 同子 process 嘅聲音，避免混入其他程式或 AI 自己嘅聲音。
- Windows application loopback 最低要求 build 20348；已查證本機係 Windows 11 Pro build 26200。
- 已查證本機有 **MOTIV Mix Virtual Input／Output** 同 Shure MV7+ 實體咪。優先評估用 MOTIV Mix 混合 AI 音訊同實體咪，讓暫停 AI 後用戶仍可自己接話；實際端點方向同混音路由需要測試。
- 後備虛擬咪候選 VB-CABLE：AI 音訊送到 playback endpoint **CABLE Input**，Discord microphone 選 recording endpoint **CABLE Output**；實體咪需要另外混音。
- 確保 AI 播音不會重新進入辨識來源；收聽同播放需要獨立管理。
- 用戶自己操作 Discord 登入及加入語音房。本機助手不使用個人帳號 token、不代登入、不自動入房或發文字訊息。
- 之後擴展多人時，需要處理混合音訊與重疊說話；目前方式不會取得參與者 user ID 或每人獨立聲軌。

來源：[Microsoft application loopback](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)、[Discord 聲音裝置設定](https://support.discord.com/hc/en-us/articles/33030151293079-Discord-Voice-Video-Streaming-Guide)、[MOTIV Mix 指南](https://www.shure.com/en-US/docs/guide/MOTIV-Mix)、[VB-CABLE](https://vb-audio.com/Cable/)。

Discord 明文禁止個人帳號 self-bot 自動化。上述音訊裝置文件證明接駁方式，並未明文批准自主 AI 透過個人帳號對答；不能將技術可行視為平台已授權。來源：[Discord self-bot 說明](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots)。

## 四種語言與候選模型

廣東話同普通話要分開辨識、生成文字及發聲，不能用「支援中文」取代廣東話驗收。

| 環節 | 首選 | 後備 | VRAM 估算 |
| --- | --- | --- | --- |
| 輪次判斷 | Silero VAD | — | 0（CPU） |
| 語音辨識 | Qwen3-ASR-1.7B | Qwen3-ASR-0.6B | 約 4 GB／約 1.5 GB |
| 對話模型 | Qwen3.5-9B Q4_K_M | Qwen3.5-4B | 約 6–7 GB／約 3–4 GB |
| 語音合成 | Fun-CosyVoice3-0.5B-2512 | OmniVoice 逐句合成 | 約 2–3 GB |

合計估算約 12–14 GB，可放入 16 GB VRAM，但餘量少；不足時先降 ASR 及對話模型。VRAM 數字係估算，未實測。

- **語音辨識**：Qwen3-ASR 官方列出 Cantonese（包括香港口音）、Chinese、Japanese、English，技術報告指 1.7B 喺廣東話對話測試成績最好。模型輸出語言判斷，可用於自動跟語言。官方串流推理只支援 vLLM backend；第一版以 VAD 確認講完後整段辨識，可用 Windows 原生 transformers 版本（`-hf` checkpoint），不需要串流 ASR。
- **對話模型**：Qwen3.5 細模型（2026 年 3 月發佈）係目前最新 4B／9B Qwen；Qwen3.6／3.8 開源最細為 27B，不適合 16 GB。Qwen3.5-9B Q4 約 5.3 GB，可用 llama.cpp／Ollama 喺 Windows 原生運行。必須關閉 thinking（`enable_thinking: false`）。細模型講廣東話容易變書面語，需要用同一組 prompt 對比 Qwen3.5-9B、Qwen3.5-4B 及 CantoneseLLMChat-v1.0-7B。
- **語音合成**：Qwen3-TTS 開源版 10 種語言同 9 個預設聲線都冇廣東話（廣東話方言只見於雲端 API），第一版不採用。CosyVoice3 文件與示例提供廣東話及串流音訊，一個模型涵蓋四語言；Windows 運行方式與實際品質待驗證。OmniVoice 官方分別列 yue、zh／cmn、ja、en，現有版本先生成完整語句，不能當作原生 streaming TTS；但配合 LLM 逐句切分合成，可以作為後備。
- 第一版只運行一個 TTS 引擎，不按語言分開兩個引擎。

來源：[Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR)、[Qwen3-ASR 技術報告](https://arxiv.org/html/2601.21337v1)、[Qwen3.5 本機運行](https://unsloth.ai/docs/models/qwen3.5)、[Qwen3.5-9B GGUF](https://huggingface.co/bartowski/Qwen_Qwen3.5-9B-GGUF)、[CantoneseLLMChat-v1.0-7B](https://huggingface.co/hon9kon9ize/CantoneseLLMChat-v1.0-7B)、[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)、[OmniVoice 語言表](https://github.com/k2-fsa/OmniVoice/blob/master/docs/languages.md)、[CosyVoice3](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512)。

現有本機 TTS 模型係可評估資源。第一版先評估通用合成聲線，再按四語言品質及回覆延遲選定。

## 輪次判斷與回覆延遲

### 延遲預算

以下係「對方講完 → AI 第一個可聽見聲音」嘅估算，未喺本機實測：

| 步驟 | 估算 | 備註 |
| --- | --- | --- |
| VAD 等靜音確認講完 | 500–800 ms | 最大單項，可調 |
| ASR 辨識一句（3–5 秒話音） | 100–300 ms | 整段辨識 |
| LLM 讀入 prompt | 50–150 ms | system prompt 及歷史需要 cache |
| LLM 生成第一句（約 10–20 tokens） | 150–300 ms | 已關 thinking |
| TTS 第一段聲 | 200–500 ms | OmniVoice 整句合成會更慢 |
| 虛擬咪 → Discord 編碼 → 網絡 → 對方 | 100–300 ms | 不受本機控制 |
| **合計** | **約 1.1–2.3 s** | |

### 減低延遲

1. **預先計算**：靜音約 300 ms 就開始 ASR 及 LLM，但不播出；對方繼續講就丟棄重做，靜音達 500–600 ms 先播。
2. **第一句短**：system prompt 要求先講短開場（例如「係呀，」「そうですね、」）；第一段喺逗號已交 TTS，之後按句號切分。
3. **預合成填充聲**：例如「嗯…」「ええと…」放喺 cache，確認講完即播，遮蓋延遲；只喺預計較慢時使用，避免不自然。
4. **模型常駐及預熱**：三個模型常駐 VRAM；llama.cpp prompt cache；限制每次回覆長度。
5. **GPU 爭用**：LLM 生成同 TTS 合成同時用 GPU 會互相拖慢，需要實測；嚴重時改用 4B 對話模型。

### 打斷

- VAD 喺 AI 播音期間持續運行；對方新話語需超過最短發言長度（例如 300 ms）先算打斷，避免「嗯」、咳嗽或 Discord 提示音截斷回覆。
- 由對方開口到 AI 停聲，預計仍有約 300–600 ms（VAD 判斷、停止播放及 Discord 緩衝）。

### 已知陷阱

- Discord 用聲音觸發收音（voice activity）時可能切走 AI 第一個音節；虛擬咪輸入靈敏度需要手動調低並測試。
- 端對端語音模型（直接聲音入、聲音出）延遲可低於 0.5 秒，但目前未找到已證實支援廣東話又放得落 16 GB 嘅本機選擇；第一版用分段流水線。

### 計時記錄

每輪記錄以下時間點，用嚟分析延遲用喺邊度：VAD 判斷講完、ASR 完成、LLM 第一個 token、第一句文字完成、TTS 第一段聲、開始播放。

## 實作次序

按風險由高至低逐步驗證，每步通過先做下一步；唔通過就先調整方案，唔好帶住問題整合。

1. **音訊路由（唔接 AI）**
   - 用 application loopback 只收 Discord 聲音，經虛擬咪播一段預錄音檔。
   - 請一位朋友喺 Discord 確認：聽到清楚、冇被降噪或聲音觸發收音切走字、冇回授；同時錄低收到嘅對方聲音，確認冇混入其他程式聲音。
   - 測試對方用喇叭嘅情況。
   - 通過條件：雙向音訊清楚，冇回授。失敗就要重新評估整條音訊路線。
2. **離線流水線**
   - 決定運行環境（Windows 原生定 WSL2）；確認 CosyVoice3 喺 Windows 跑唔跑到，唔得就改用 OmniVoice 逐句合成。
   - 四種語言各準備幾段錄音，測 ASR 準確度、LLM 回覆自然度（包括廣東話口語對比）、TTS 發音。
   - 量度延遲預算表每一格嘅實數，同時睇 VRAM 用量。
   - 通過條件：四語言質素可接受；估算總延遲接近驗收目標。
3. **整合即時對話**
   - 加入 VAD、預先計算、逐句合成、打斷及語言自動切換／鎖定。
   - 先用本機錄音模擬對方測試，再做真人一對一 Discord 測試。
4. **控制台及操作**
   - 繁中網頁控制台（啟用／停止、裝置、語言、狀態）及快捷鍵暫停／恢復。
   - 完成後按下面驗收逐項測試。

## 驗收

1. 在正常 Discord 語音房收聽真人，對方亦聽到 AI 回覆。
2. 四種語言分別測試說話辨識、自然回覆及發音；廣東話不能以普通話結果代替。
3. 自動切換語言，同時可以手動鎖定。
4. 記錄「對方講完 → AI 第一個可聽見聲音」嘅實測延遲；單一模型生成速度不能代替整段延遲。目標：中位數 ≤ 1.5 s，理想 ≤ 1.0 s；同時報告最差值及各步驟分項時間。
5. AI 播音期間保持聆聽，收到對方新話語後停止舊回覆；短促聲音（例如「嗯」、咳嗽）不會觸發打斷。
6. 不會自我接話、循環播音或將其他程式聲音當作對方語音。
7. 快捷鍵暫停後 AI 不回應；用戶可以自己說話，再恢復 AI。
8. 不保存第一版會話錄音／逐字稿；不產生雲端 AI API 計費。

模型支援表、離線樣本或程式檢查不能代替實際 Discord 語音驗收。首次真人測試需要確認音訊裝置、正常客戶端及一位對話參與者。

## 後續階段

多人對話、錄音／逐字稿／分析、實際電話打出／接聽及雲端 AI 模式留待後續決定。
