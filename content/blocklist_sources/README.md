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

```
Schedule Trigger (cron: 0 8 * * *)
  → HTTP Request 抓 165 打詐儀表板 / data.gov.tw 警政署開放資料
  → 整理成上面的 CSV
  → Write Binary File 寫到本資料夾
  → Execute Command: python tools/sync_blocklist.py
```

> 只爬「官方／政府開放資料」。請勿爬 Whoscall、防詐達人等商業服務（違反服務條款且有反爬蟲）。
