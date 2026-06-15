# 黑名單來源投放夾

把官方詐騙資料整理成 CSV 放在這個資料夾，執行 `python tools/sync_blocklist.py`
就會併入 `../blocklist.json`（分析時優先比對，命中即標「已被通報」高風險）。

CSV 格式（有標頭）：

```csv
type,value
domain,shopee-evil.xyz
phone,0912345678
url,http://fake.example/login
```

- `type`：`domain`（網域）/ `url`（完整網址）/ `phone`（電話，0 開頭或 +國碼皆可）。
- 也接受「無標頭的單欄清單」，腳本會自動判斷類型。

## n8n 每天 08:00 自動更新（建議）

已提供可直接匯入的排程 workflow：**`n8n/blocklist_sync_workflow.json`**

```
Schedule Trigger (cron: 0 8 * * *)
  → Execute Command: python tools/sync_blocklist.py
```

`tools/sync_blocklist.py` 已內建 data.gov.tw 官方涉詐網域資料集的 HTTP 抓取，
直接排程即可；若想用純 n8n 節點抓取再投 CSV，可改成：

```
Schedule Trigger (cron: 0 8 * * *)
  → HTTP Request 抓 data.gov.tw 警政署開放資料
  → 整理成上面的 CSV
  → Write Binary File 寫到本資料夾
  → Execute Command: python tools/sync_blocklist.py
```

匯入細節（工作目錄、權限、離線替代）見 `n8n/import_notes.md`。

> 只爬「官方／政府開放資料」。請勿爬 Whoscall、防詐達人等商業服務（違反服務條款且有反爬蟲）。
