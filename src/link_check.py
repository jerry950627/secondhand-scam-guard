"""連結與電話查核：把「話術判斷」補上「黑名單比對」的能力。

完全離線可跑：用啟發式規則判斷網址/電話風險，並自動產生可一鍵查證的
官方查詢連結（165、Google 安全瀏覽、VirusTotal）。
若設定環境變數 SCAM_SAFEBROWSING_KEY，會額外實際呼叫 Google Safe Browsing API。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RISK_ORDER = {"無": -1, "低": 0, "中": 1, "高": 2}

BLOCKLIST_PATH = Path(__file__).resolve().parents[1] / "content" / "blocklist.json"


def _phone_key(raw: str) -> str:
    """電話正規化：去非數字、台灣 0 開頭轉 886，方便黑名單比對。"""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "886" + digits[1:]
    return digits


@lru_cache(maxsize=1)
def load_blocklist() -> dict:
    """讀取本地黑名單快取（由排程每天更新）；檔案不存在時回傳空集合，不影響運作。"""
    try:
        with BLOCKLIST_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    return {
        "domains": {str(d).lower() for d in data.get("domains", [])},
        "urls": {str(u).lower() for u in data.get("urls", [])},
        "phones": {_phone_key(str(p)) for p in data.get("phones", [])},
        "updated_at": data.get("updated_at", ""),
    }


def _domain_in_blocklist(host: str, domains: set) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)

# 官方/可信網域（後綴比對）。出現品牌字但網域不在此清單＝疑似冒用。
OFFICIAL_DOMAINS = (
    "shopee.tw", "shopee.com", "xiapibuy.com", "momoshop.com.tw", "pchome.com.tw",
    "pcstore.com.tw", "ruten.com.tw", "books.com.tw", "7-11.com.tw", "family.com.tw",
    "ibon.com.tw", "t-cat.com.tw", "ecpay.com.tw", "newebpay.com", "post.gov.tw",
    "165.npa.gov.tw", "npa.gov.tw", "gov.tw", "line.me", "google.com", "facebook.com",
)
# 品牌關鍵字（latin）：出現在網域但非官方 → 冒用。
BRAND_KEYWORDS = ("shopee", "momo", "pchome", "ruten", "ecpay", "newebpay", "7-11", "family", "ibon")
# 常見短網址服務（目的地不明）。
SHORTENERS = (
    "bit.ly", "reurl.cc", "lihi.cc", "lihi1.cc", "lihi2.cc", "lihi3.cc", "lihi.tv",
    "pse.is", "tinyurl.com", "ppt.cc", "0rz.tw", "goo.gl", "t.co", "is.gd", "cutt.ly",
    "myppt.cc", "risu.io", "reurl.com",
)
# 詐騙常見可疑 TLD。
SUSPICIOUS_TLDS = (
    "xyz", "top", "icu", "vip", "tk", "ml", "ga", "cf", "gq", "buzz", "click",
    "rest", "work", "fit", "cyou", "sbs", "shop",
)

URL_RE = re.compile(r"(?:https?://|www\.)[^\s，。、！？；：)）\]】<>\"'　]+", re.IGNORECASE)
IP_HOST_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
# 國際號碼（含境外詐騙）/ 台灣手機 / 0800。刻意保守，避免誤抓金額。
PHONE_RE = re.compile(
    r"(?<![\w+])\+\d[\d\s-]{6,14}\d"
    r"|(?<!\d)09\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"
    r"|(?<!\d)0800[-\s]?\d{3}[-\s]?\d{3}(?!\d)"
)

SAFE_BROWSING_ENDPOINT = "https://safebrowsing.googleapis.com/v4/threatMatches:find"


@dataclass(frozen=True)
class ArtifactFinding:
    kind: str  # "url" | "phone"
    value: str
    level: str  # 無/低/中/高
    reason: str
    lookup: tuple  # ((label, href), ...)


def _host_of(url: str) -> str:
    candidate = url if "://" in url else "http://" + url
    try:
        host = urllib.parse.urlparse(candidate).hostname or ""
    except ValueError:
        host = ""
    return host.lower().lstrip(".")


def _is_official(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


def _tld_of(host: str) -> str:
    return host.rsplit(".", 1)[-1] if "." in host else ""


def _url_lookup_links(url: str) -> tuple:
    enc = urllib.parse.quote(url, safe="")
    return (
        ("Google 安全瀏覽查詢", f"https://transparencyreport.google.com/safe-browsing/search?url={enc}"),
        ("VirusTotal 掃描", f"https://www.virustotal.com/gui/search/{urllib.parse.quote_plus(url)}"),
        ("165 打詐儀表板", "https://165dashboard.tw/"),
    )


def _phone_lookup_links(phone: str) -> tuple:
    digits = re.sub(r"\D", "", phone)
    return (
        ("Whoscall 查號", f"https://whoscall.com/zh-hant/number/886{digits.lstrip('0')}"),
        ("Google 查「此號碼+詐騙」", f"https://www.google.com/search?q={urllib.parse.quote(phone + ' 詐騙')}"),
        ("165 全民防騙網", "https://165.npa.gov.tw/"),
    )


def _safe_browsing(url: str, api_key: str) -> bool | None:
    """有設 key 時實際查 Google Safe Browsing；回傳 True=命中、False=未命中、None=查詢失敗。"""
    payload = {
        "client": {"clientId": "scam-guard", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{SAFE_BROWSING_ENDPOINT}?key={urllib.parse.quote(api_key)}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=6) as response:
            result = json.loads(response.read().decode("utf-8"))
        return bool(result.get("matches"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def assess_url(url: str, api_key: str = "") -> ArtifactFinding:
    host = _host_of(url)
    lookup = _url_lookup_links(url)

    # 黑名單優先：命中官方通報名單即為高信心「已被通報」。
    blocklist = load_blocklist()
    if url.lower() in blocklist["urls"] or (host and _domain_in_blocklist(host, blocklist["domains"])):
        return ArtifactFinding("url", url, "高", "已列入詐騙黑名單（官方通報）", lookup)

    if api_key:
        hit = _safe_browsing(url, api_key)
        if hit:
            return ArtifactFinding("url", url, "高", "Google Safe Browsing 標記為惡意網址", lookup)

    if not host:
        return ArtifactFinding("url", url, "中", "無法解析網域，建議自行查證", lookup)
    if IP_HOST_RE.match(host):
        return ArtifactFinding("url", url, "高", "以原始 IP 位址連線，正常賣場不會這樣", lookup)
    if _is_official(host):
        return ArtifactFinding("url", url, "低", f"屬已知官方網域（{host}）", lookup)
    if any(brand in host for brand in BRAND_KEYWORDS):
        return ArtifactFinding("url", url, "高", f"網域夾帶品牌字卻非官方（{host}），疑似冒用釣魚", lookup)
    if any(host == s or host.endswith("." + s) for s in SHORTENERS):
        return ArtifactFinding("url", url, "中", "短網址隱藏真實目的地，詐騙常用", lookup)
    if _tld_of(host) in SUSPICIOUS_TLDS:
        return ArtifactFinding("url", url, "中", f"使用高風險網域結尾（.{_tld_of(host)}）", lookup)
    return ArtifactFinding("url", url, "低", f"非已知官方網域（{host}），請點連結自行查證", lookup)


def assess_phone(phone: str) -> ArtifactFinding:
    lookup = _phone_lookup_links(phone)
    if _phone_key(phone) in load_blocklist()["phones"]:
        return ArtifactFinding("phone", phone, "高", "已列入詐騙黑名單（官方通報）", lookup)
    normalized = phone.strip()
    if normalized.startswith("+") and not normalized.startswith("+886"):
        return ArtifactFinding("phone", phone, "高", "境外來電號碼，二手交易少見", lookup)
    if normalized.startswith("0800"):
        return ArtifactFinding("phone", phone, "中", "0800 客服號碼常被冒用，請查證", lookup)
    return ArtifactFinding("phone", phone, "低", "請用 Whoscall / 165 查此號碼是否被通報", lookup)


def check_text(text: str, api_key: str | None = None) -> dict:
    """抽出文字中的網址與電話並查核，回傳結構化結果與整體風險。"""
    api_key = os.environ.get("SCAM_SAFEBROWSING_KEY", "") if api_key is None else api_key
    findings: list[ArtifactFinding] = []

    seen_urls = set()
    url_spans: list[tuple[int, int]] = []
    for match in URL_RE.finditer(text):
        url_spans.append((match.start(), match.end()))
        url = match.group(0).rstrip(".)）」』,")
        if url.lower() in seen_urls:
            continue
        seen_urls.add(url.lower())
        findings.append(assess_url(url, api_key))

    seen_phones = set()
    for match in PHONE_RE.finditer(text):
        # 落在網址內的數字串（如 URL path 含 09 開頭號碼）不另列為電話，避免重複誤報。
        if any(start <= match.start() and match.end() <= end for start, end in url_spans):
            continue
        phone = match.group(0).strip()
        key = re.sub(r"\D", "", phone)
        if key in seen_phones:
            continue
        seen_phones.add(key)
        findings.append(assess_phone(phone))

    max_level = "無"
    for finding in findings:
        if RISK_ORDER[finding.level] > RISK_ORDER[max_level]:
            max_level = finding.level

    return {
        "整體連結電話風險": max_level,
        "項目": [
            {
                "類型": f.kind,
                "內容": f.value,
                "風險": f.level,
                "原因": f.reason,
                "查證連結": [{"label": label, "href": href} for label, href in f.lookup],
            }
            for f in findings
        ],
    }
