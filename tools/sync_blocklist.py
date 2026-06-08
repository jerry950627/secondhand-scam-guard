"""更新本地詐騙黑名單 content/blocklist.json。

兩種資料來源（都可由 n8n 每天 08:00 觸發）：

1. 本地 CSV 投放（最簡單、可離線測）：
   把官方資料整理成 CSV 放到 content/blocklist_sources/*.csv，欄位：
       type,value
       domain,shopee-evil.xyz
       phone,0912345678
       url,http://fake.example/login
   n8n 可用「Write Binary File」把抓到的官方資料寫成 CSV 丟這裡。

2. HTTP 來源（選配，需連網）：在 HTTP_SOURCES 填官方 CSV/JSON 端點
   （例如 data.gov.tw 警政署詐騙網址開放資料集）。抓不到不會清空既有名單。

用法：
    python tools/sync_blocklist.py            # 從 CSV 投放夾 + HTTP 來源更新
    python tools/sync_blocklist.py --add domain shopee-evil.xyz
    python tools/sync_blocklist.py --add phone 0912345678
"""

from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKLIST_PATH = ROOT / "content" / "blocklist.json"
SOURCES_DIR = ROOT / "content" / "blocklist_sources"

VALID_TYPES = {"domain": "domains", "url": "urls", "phone": "phones"}

# 官方 CSV 端點（政府開放資料）。抓不到會略過、不清空既有名單。
# 預設接「165 反詐騙_遭停止解析涉詐網站」（data.gov.tw dataset 176455，約 5.8 萬筆詐騙網域，欄位含「網域」）。
HTTP_SOURCES: list[str] = [
    "https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/"
    "29E8E643-88ED-4952-B21E-BD42A3B7108C/resource/AF8F641E-B64A-4538-B457-8F7512990278/download",
]

# 欄位名稱關鍵字 → 類型（自動偵測任意官方 CSV 的欄位）。
DOMAIN_COLS = ("網域", "domain", "website", "site")
URL_COLS = ("網址", "url", "weburl", "link")
PHONE_COLS = ("電話", "號碼", "phone", "tel")


def load_blocklist() -> dict:
    try:
        with BLOCKLIST_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"domains": [], "urls": [], "phones": [], "sources": []}


def _classify_value(value: str) -> str | None:
    """依內容判斷一筆是網址/網域/電話。"""
    value = value.strip()
    if not value:
        return None
    stripped = value.replace("+", "").replace("-", "").replace(" ", "")
    if stripped.isdigit() and 6 <= len(stripped) <= 15:
        return "phones"
    if "://" in value or "/" in value:
        return "urls"
    if "." in value and " " not in value and "@" not in value:
        return "domains"
    return None


def _ingest_csv_text(text: str, buckets: dict[str, set]) -> int:
    added = 0
    reader = csv.DictReader(io.StringIO(text))
    fields = [f.strip() for f in (reader.fieldnames or [])]
    lower = {f.lower() for f in fields}

    # 1) 自家格式 type,value
    if {"type", "value"}.issubset(lower):
        for row in reader:
            kind = (row.get("type") or "").strip().lower()
            value = (row.get("value") or "").strip()
            bucket = VALID_TYPES.get(kind)
            if bucket and value:
                buckets[bucket].add(value)
                added += 1
        return added

    # 2) 官方 CSV：依欄位名稱自動挑出網域/網址/電話欄
    target_cols = [
        f for f in fields
        if any(k in f or k in f.lower() for k in DOMAIN_COLS + URL_COLS + PHONE_COLS)
    ]
    if target_cols:
        for row in reader:
            for col in target_cols:
                bucket = _classify_value(row.get(col) or "")
                if bucket:
                    buckets[bucket].add((row.get(col) or "").strip())
                    added += 1
        return added

    # 3) 無標頭單欄清單：逐列自動判斷
    for line in text.splitlines():
        bucket = _classify_value(line)
        if bucket and line.strip().lower() not in {"domain", "url", "phone", "value"}:
            buckets[bucket].add(line.strip())
            added += 1
    return added


def ingest_local_csv(buckets: dict[str, set]) -> int:
    if not SOURCES_DIR.exists():
        return 0
    total = 0
    for path in sorted(SOURCES_DIR.glob("*.csv")):
        try:
            total += _ingest_csv_text(path.read_text(encoding="utf-8-sig"), buckets)
            print(f"  讀取 {path.name}")
        except OSError as exc:
            print(f"  略過 {path.name}（{exc}）")
    return total


def ingest_http(buckets: dict[str, set]) -> int:
    total = 0
    for url in HTTP_SOURCES:
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                text = response.read().decode("utf-8", errors="replace")
            total += _ingest_csv_text(text, buckets)
            print(f"  抓取 {url}")
        except Exception as exc:  # noqa: BLE001 - 任一來源失敗都不應中斷
            print(f"  來源失敗，略過：{url}（{exc}）")
    return total


def write_blocklist(existing: dict, buckets: dict[str, set]) -> None:
    merged = {
        "updated_at": datetime.date.today().isoformat(),
        "note": existing.get("note", "本地黑名單快取，由 tools/sync_blocklist.py 更新。"),
        "sources": existing.get("sources", []),
        "domains": sorted(buckets["domains"]),
        "urls": sorted(buckets["urls"]),
        "phones": sorted(buckets["phones"]),
    }
    BLOCKLIST_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="更新本地詐騙黑名單")
    parser.add_argument("--add", nargs=2, metavar=("TYPE", "VALUE"), help="手動加一筆：domain/url/phone 值")
    args = parser.parse_args()

    existing = load_blocklist()
    buckets = {
        "domains": set(existing.get("domains", [])),
        "urls": set(existing.get("urls", [])),
        "phones": set(existing.get("phones", [])),
    }
    before = sum(len(v) for v in buckets.values())

    if args.add:
        kind, value = args.add[0].lower(), args.add[1].strip()
        bucket = VALID_TYPES.get(kind)
        if not bucket:
            print(f"未知類型「{kind}」，需為 domain / url / phone。")
            sys.exit(1)
        buckets[bucket].add(value)
        print(f"已加入 {kind}: {value}")
    else:
        print("從本地 CSV 投放夾更新…")
        ingest_local_csv(buckets)
        if HTTP_SOURCES:
            print("從 HTTP 來源更新…")
            ingest_http(buckets)

    write_blocklist(existing, buckets)
    after = sum(len(v) for v in buckets.values())
    print(
        f"完成：黑名單 {before} → {after} 筆"
        f"（網域 {len(buckets['domains'])}／網址 {len(buckets['urls'])}／電話 {len(buckets['phones'])}）"
    )


if __name__ == "__main__":
    main()
