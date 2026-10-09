# 後續選項費用查證

查證日期：2026-10-09。費率係文件快照，實際付款前需要重新確認；尚未購買號碼、開通服務或進行收費通話。

目前第一版已改為四語言本機即時對話，不使用雲端 AI API，亦不申請電話號碼。以下資料留作後續選項比較。

## GPT-Live 1

精確模型名稱：`gpt-live-1`。官方語音 session 費率為 **US$0.05／分鐘，按秒計費**。Backend 模型同工具費另外計。

| Active session 時間 | 語音部分費用 |
| --- | --- |
| 1 分鐘 | US$0.05 |
| 5 分鐘 | US$0.25 |
| 10 分鐘 | US$0.50 |
| 60 分鐘 | US$3.00 |

Session 開住期間，聽、講、雙方靜音及等候 backend 都計入時間。估算使用 session 由開始至關閉嘅時間，而非只計有人講嘢嘅時間。

電話號碼租用、電話通話費及其他服務並不包含在上表。美元金額未換算日圓，亦未驗證用戶帳戶嘅實際模型或 SIP 存取權限。

來源：[模型文件](https://developers.openai.com/api/docs/models/gpt-live-1)、[計費說明](https://developers.openai.com/api/docs/guides/voice-latency-cost)。

## 日本電話接駁與 ¥1,000 月費上限

目前未能核實一條個人可以申請、支援實際來電及撥出、可整合 AI 音訊，而且完整費用符合上限嘅路線。呢個係資格及報價仍有缺口，並非已證明沒有合適服務。

- **Twilio 050**：官方列 US$4.75／月，另有來電、撥出及可選串流／錄音費。目前日本申請文件要求公司證明，未核實普通個人資格。
- **Telnyx**：日本頁面列本地號碼由 US$5／月起；國內 national number 文件提供個人身份審核要求，但未核實呢種號碼嘅完整報價、帳戶權限或實際供應。
- **My050**：¥550 初始費及 ¥550／六個月維持費，兩者首次在第 9 日扣除，即 ¥1,100，尚未計付費通話。頁面提及第三方 softphone／adapter 不在支援範圍，同時服務條款有使用方式限制；私人 AI SIP client 嘅適用性需要供應商澄清。

來源：[Twilio 日本費率](https://www.twilio.com/en-us/voice/pricing/jp)、[Twilio 日本申請要求](https://www.twilio.com/en-us/guidelines/jp/regulatory)、[Telnyx 日本號碼](https://telnyx.com/phone-numbers/japan)、[Telnyx 日本號碼要求](https://support.telnyx.com/en/articles/15444978-japan-did-requirements)、[My050 官方頁面](https://www.brastel.com/my050/jpn/)。

若首月也包括在 ¥1,000 硬上限內，My050 已查證嘅初始扣款會超出上限。其他路線仍需確認租用、初始、來電、撥出、計費單位、稅項及付款匯率後，先可以估算可用分鐘數。
