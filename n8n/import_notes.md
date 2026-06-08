# n8n 匯入說明

匯入 `secondhand_scam_guard_workflow.json` 後，可以先用 Webhook 測試文字輸入：

```json
{
  "text": "買家說無法下單，要求我加 LINE 客服並操作網路銀行做金流驗證"
}
```

目前匯入版 workflow（v2）的 Code node 已與本機 Python 引擎邏輯同步：含 NFKC 正規化、同義詞、拆字規避 compact 比對、中文 bigram RAG、10 類知識庫、HyDE 僅展示不計分、低風險只引用安全守則，以及原文話術標註（`highlights`）。確保沒有 API key 也能示範完整 pseudo-query、HyDE 與 RAG 風險分析。

> 內嵌的 JS 已用 QuickJS（ES2020）實跑，與 Python 引擎在低/中/高、拆字規避、同義詞、解除分期、假投資、正常 COD 等案例上輸出完全一致。pinData 預設帶一筆拆字規避測試輸入，匯入後可直接執行查看結果。

若要升級為真 VLM/LLM：

1. 在 Webhook 後加入 Gemini VLM node，讓它讀截圖並輸出 `vlm_text`。
2. 將 `vlm_text` 傳給 Code node 或 AI Agent。
3. 用 Simple Vector Store 或 Qdrant 取代 Code node 裡的 `knowledgeBase`。
4. 高風險時新增 Google Sheet、Email、LINE Notify 或 Telegram 節點做自動通知。

PowerShell 或命令列測試時，若輸入 `NT$2500` 這類金額，請使用單引號或跳脫 `$`，避免金額被 shell 當成變數處理。

---

## 進階：黑名單比對、定時同步、釣魚頁檢查（設計）

> 以下三項需外部網路 / API key，無法在本機離線實跑，故以「節點設計」提供。
> 本機 App 已內建 ①（離線啟發式版），這裡是 n8n 自動化的升級路徑。

### ① 抽出網址/電話 → 查黑名單（本機 App 已內建）
- 本機已由 `src/link_check.py` 做：抽 URL/電話 → 啟發式判斷（冒用品牌、原始 IP、短網址、可疑 TLD、境外電話）→ 產生 165／Google 安全瀏覽／VirusTotal 查證連結。
- 若設環境變數 `SCAM_SAFEBROWSING_KEY`，會實際呼叫 Google Safe Browsing API。
- n8n 版可在 Code node 後加 **HTTP Request → Google Safe Browsing**（`POST /v4/threatMatches:find?key=...`）對抽出的網址做雲端比對。

### ② 定時同步 165 公告 → 擴充知識庫
1. **Schedule Trigger**（cron，例如每日 08:00）。
2. **HTTP Request** 抓 165 全民防騙網的最新文章列表 / RSS。
3. **AI Agent / LLM 節點**（Gemini 或本機 Ollama）把文章內容萃取成結構化
   `{title, risk_signals[], guidance, source_url}`。
4. **Code/Merge** 去重後，寫回 `content/anti_fraud_knowledge_base.json`
   （或寫入 Vector Store）。
5. 解決「知識庫不會自動更新」的缺口。

### ③ URL 爬取 + VLM 看釣魚頁
1. 從輸入抽出網址（同 ①）。
2. **HTTP Request** 抓該網址 HTML，或用無頭瀏覽器截圖。
3. **Gemini VLM** 看截圖/HTML 判斷是否為冒名登入頁、假金流頁。
4. 把結果併入風險分數。

> 自動分流（OCR↔VLM）：在 ② 之外，可在 OCR 節點後加一個 **IF 節點**——
> 當 OCR 抽出的字數過少或信心過低，就改走 Gemini VLM 重新讀圖。
