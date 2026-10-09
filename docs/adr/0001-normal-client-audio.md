---
status: proposed
---

# 第一版以正常 Discord 客戶端音訊接駁

用戶要求使用自己嘅 Discord 帳號，手動入語音房，所有 AI 推理喺本機進行。因此第一版評估 Windows application loopback 收音及虛擬咪播音，Discord 登入同入房由用戶操作。與 bot 帳號接駁相比，呢條路線配合用戶現有身份，但只有客戶端混合音訊，沒有個別 user ID／聲軌，亦需要管理音訊回授、實體咪及 AI 聲音路由；第一版先一對一驗收。

音訊接駁文件並未建立平台對自主 AI 個人帳號對答嘅明確許可，保留呢個界限。來源：[Microsoft application loopback](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)、[Discord self-bot 說明](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots)。
