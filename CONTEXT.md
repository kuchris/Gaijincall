# Gaijincall

Gaijincall 係一個本機多語言語音對話助手。目前討論以用戶自己嘅 Discord 語音會話為場景。

## Language

**AI 語音助手（AI voice assistant）**:
聆聽其他參與者嘅聲音並以合成語音進行對話嘅 AI 代理。
_Avoid_: 將純文字聊天稱為語音對話

**Discord 語音會話（Discord voice conversation）**:
用戶使用自己嘅 Discord 帳號，在語音房中同其他參與者進行嘅聲音交流。
_Avoid_: 將 Discord 語音會話稱為電話號碼接駁

**對方語音（Incoming participant speech）**:
其他參與者傳畀用戶嘅聲音。
_Avoid_: 將 AI 自身播出嘅聲音當成對方語音

**AI 回覆語音（Assistant speech）**:
由助手生成並用作回覆對方嘅聲音。
_Avoid_: 將尚未播出嘅文字稱為已說出嘅回覆

**即時對話（Realtime conversation）**:
持續聆聽並逐輪以語音回應嘅會話；對方新話語可以打斷未完成嘅 AI 回覆。
_Avoid_: 將單段錄音嘅批次處理當成即時會話已完成驗收

**AI 對話模式（AI conversation mode）**:
由用戶開啟、允許助手自動聆聽及語音回應嘅狀態；用戶可以暫停或停止。
_Avoid_: 將登入 Discord 視為已啟用 AI 對話

**對話語言（Conversation language）**:
對方話語及 AI 回覆使用嘅語言；本專案分別處理廣東話、普通話、日文及英文。
_Avoid_: 將廣東話同普通話混稱為同一種語言

**語言鎖定（Language lock）**:
用戶指定 AI 固定以一種支援語言回覆嘅選擇。
_Avoid_: 將自動偵測語言視為已鎖定

**回覆延遲（Reply latency）**:
對方一輪話音結束，到 AI 第一個可聽見聲音開始嘅時間。
_Avoid_: 用單一模型嘅生成時間代替整段對話回覆延遲
