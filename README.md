# FB/Threads 二手交易 AI 防踩雷助理

這份期末專案把 RAG、pseudo-query、HyDE、LLM、VLM 與 n8n 放進一個生活化場景：使用者上傳二手交易貼文或對話截圖，系統判斷是否有假買家、假客服、金流驗證、私下加 LINE、釣魚物流連結等風險。

> 📖 系統如何運作、資料來源與完整流程：見 **[HOW_IT_WORKS.md](HOW_IT_WORKS.md)**。

## 架構

採**混合式**研判，兩層互補：

1. **離線規則引擎（永遠執行）**：pseudo-query → HyDE → RAG 檢索 → 分級，完全離線、可解釋、附 165／警政署等真實來源引用。輸入會先經過正規化（全形轉半形、拆字規避還原如「金．流．驗．證」、同義詞如「轉帳→匯款」「加賴→LINE」），中文以 bigram 斷詞讓 RAG 重疊真正生效。
2. **4B LLM 語意研判（可選）**：偵測到本機有 LLM 時自動加入，抓規則漏掉的新話術與規避手法；融合時**取較高風險**（保守）。連不到模型就自動降級為純規則模式，demo 不會壞。

## 主要功能

- **10 類詐騙知識庫**：假買家、假客服金流驗證、釣魚物流、私下交易、異常低價、**解除分期付款（台灣最常見）**、貨到付款換包裹、假投資、代購代儲，外加正常交易守則參考。
- **原文話術標註**：在原文中標色出觸發風險的字句，連拆字規避（金．流．驗．證）都能標出位置。
- **連結與電話查核（黑名單比對）**：自動抽出網址/電話，**先比對官方黑名單**（5.8 萬筆 165／刑事局詐騙網域，由 `tools/sync_blocklist.py` 同步），命中即標「已被通報」；沒命中再用啟發式（冒用品牌、原始 IP、短網址、境外電話）+ 話術/LLM 判斷，並附 165／Google 安全瀏覽／VirusTotal 一鍵查證連結。
- **截圖 OCR**：以 tesseract.js 在前端離線辨識繁中截圖文字（首次使用需連網下載語言包），自動清理介面雜訊。
- **規則 vs LLM 對照**：並排顯示兩種研判，呈現混合式價值。
- **漸進式渲染**：規則結果毫秒級先顯示，4B LLM 研判完再更新。
- **報告匯出**：JSON / 文字報告下載、複製摘要與查證問題、列印/匯出 PDF。

## 繳交內容

- `presentation/二手交易AI防踩雷助理.pptx`：7 頁期末簡報。
- `n8n/secondhand_scam_guard_workflow.json`：可匯入 n8n 的 workflow 範本。
- `HOW_IT_WORKS.md`：系統運作邏輯與資料來源完整說明。
- `content/anti_fraud_knowledge_base.json`：RAG 知識庫資料（10 類，含正常交易參考）。
- `content/blocklist.json`：本地詐騙黑名單快取（官方來源，可每天同步）。
- `content/test_cases.json`：低/中/高、拆字規避、同義詞、正常交易等測試案例。
- `src/scam_guard_demo.py`：orchestrator，融合規則 + LLM + 黑名單查核。
- `src/rules_engine.py`：離線規則引擎（pseudo-query + HyDE + RAG）。
- `src/text_normalize.py`：正規化、同義詞、拆字規避、中文 bigram 斷詞、話術標註。
- `src/link_check.py`：連結/電話查核（黑名單優先 → 啟發式 → 查證連結）。
- `src/llm_client.py`：可選 4B LLM 用戶端（Ollama / OpenAI 相容，純標準庫）。
- `tools/sync_blocklist.py`：從官方開放資料更新黑名單（可由 n8n 排程）。
- `tests/test_scam_guard.py`：pytest 測試（37 項）。

## 本機測試

快速分級檢查（無需 pytest）：

```powershell
python src\scam_guard_demo.py --test
```

完整單元 / 整合測試：

```powershell
python -m pytest tests\ -v
```

## 接 4B LLM（gemma3:4b）

本機已安裝 **免安裝版 Ollama** 於 `C:\Users\USER\Downloads\ollama`，模型 `gemma3:4b`（Q4_K_M，約 3.3GB）放在 `Downloads\ollama\models`。

啟動 Ollama（最方便）：

```powershell
.\Start-Ollama.ps1
```

或手動：

```powershell
$env:OLLAMA_MODELS = "C:\Users\USER\Downloads\ollama\models"
& "C:\Users\USER\Downloads\ollama\ollama.exe" serve
```

接著以 LLM 模式啟動分析伺服器：

```powershell
$env:SCAM_LLM_ENABLED = "1"
$env:SCAM_LLM_TIMEOUT = "120"
python server.py
```

伺服器啟動時會**背景預熱**模型，第一個請求就不必承受冷啟動（實測預熱後每次分析約 4–5 秒，Vulkan GPU 推論）。報告會顯示「4B LLM 模式」與規則 vs LLM 對照。

可用環境變數調整：

```powershell
$env:SCAM_LLM_MODEL = "qwen3:4b"          # 換模型（中文更強）
$env:SCAM_LLM_API = "openai"              # 改走 OpenAI 相容端點（如 LM Studio）
$env:SCAM_LLM_BASE_URL = "http://localhost:1234"
$env:SCAM_LLM_ENABLED = "0"               # 強制純規則模式
```

用 `http://127.0.0.1:8765/api/health` 確認 `llm_available` 狀態。

**融合策略**：規則引擎永遠跑（離線、可解釋、附 RAG 引用），LLM 在可用時加入並**取較高風險**（保守）。實測 LLM 能抓到規則漏掉的無關鍵字話術，例如「直接匯到私人帳號繞過平台」規則判低、LLM 判高 → 綜合取高。LLM 失敗會自動重試一次，仍失敗則降級純規則模式。

## 線上部署（Render + Groq，永久公開連結）

可把 `server.py`（同時提供 API 與前端）部署到 Render 免費方案，取得固定公開網址讓任何人直接使用。雲端沒有本機 Ollama，改接 **Groq** 的免費 OpenAI 相容 API 提供語意研判；連不到或未設 key 時會自動降級為純規則模式，服務不會壞。

1. **申請 Groq 免費 key**：<https://console.groq.com/keys> 註冊並建立 API key（`gsk_...`）。
2. **用 Blueprint 部署**：<https://render.com> 以 GitHub 登入 → **New → Blueprint** → 選此 repo → **Apply**（會讀取 `render.yaml`）。
3. **填入金鑰**：部署時 Dashboard 會要求 `SCAM_LLM_API_KEY`，貼上 Groq key。
4. 約 2–3 分鐘後取得固定網址（免費方案閒置會休眠，首次喚醒約 30–50 秒）。

> 線上 demo：（部署完成後把網址填在這裡）

模型可在 `render.yaml` 的 `SCAM_LLM_MODEL` 調整（預設 `llama-3.3-70b-versatile`）。

## 啟動本機 UI

最方便的方式：

```powershell
.\Start-UI.ps1
```

停止本機 UI：

```powershell
.\Stop-UI.ps1
```

手動啟動方式：

```powershell
python server.py
```

啟動後打開：

```text
http://127.0.0.1:8765
```

使用方式：

1. 可先把交易截圖拖到 UI、選擇圖片，或直接貼上圖片，作為本機預覽。
2. 將 FB/Threads 二手交易貼文、私訊內容，或 VLM/OCR 從截圖抽出的文字貼到文字欄位。
3. 按「分析風險」。
4. 查看風險等級、可疑訊號、RAG 引用依據、建議行動與查證問題。
5. 需要保留結果時，可下載文字報告、下載 JSON、複製摘要或列印成 PDF。

截圖可按「辨識文字」用本機 OCR（tesseract.js）自動轉文字；要更強的「看懂圖」可接 n8n 的 Gemini VLM 節點。為什麼本機用 OCR 而非 VLM（離線/隱私/準度取捨）見 HOW_IT_WORKS。

## 更新詐騙黑名單

本地黑名單 `content/blocklist.json` 可從官方開放資料更新（預設接 165／刑事局「遭停止解析涉詐網站」約 5.8 萬筆）：

```powershell
python tools\sync_blocklist.py            # 從官方來源 + 本地 CSV 更新
python tools\sync_blocklist.py --add domain shopee-evil.xyz  # 手動加一筆
```

可由 n8n「Schedule（每天 08:00）→ Execute Command」自動執行。只爬官方/政府開放資料，不爬 Whoscall 等商業服務。

## Demo 指令

```powershell
python src\scam_guard_demo.py "買家說無法下單，要求我加 LINE 客服並操作網路銀行做金流驗證"
```

PowerShell 若輸入含有 `NT$2500` 這種金額，建議用單引號包住整段文字，避免 `$2500` 被當成變數展開。
