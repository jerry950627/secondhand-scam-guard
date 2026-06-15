"""離線規則引擎：pseudo-query + HyDE + RAG 風險研判。

完全離線、可解釋、附 RAG 引用依據。LLM 不可用時即以此為準。
所有比對都經過 text_normalize 處理，容忍全形、拆字規避與同義詞。
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import embeddings
from text_normalize import (
    PreparedText,
    highlight_spans,
    match_terms,
    prepare,
    tokenize,
)

ROOT = Path(__file__).resolve().parents[1]
KB_PATH = ROOT / "content" / "anti_fraud_knowledge_base.json"
TEST_CASES_PATH = ROOT / "content" / "test_cases.json"
KB_EMBED_CACHE_PATH = ROOT / "content" / "kb_embeddings.json"

# --- 語境與話術詞表 -------------------------------------------------
# 出現這些片語代表使用者本身採取了安全做法，需抑制相關誤判。
SAFE_PAYMENT_PHRASES = (
    "不接受先匯款",
    "不先匯款",
    "可面交",
    "現場測試",
    "平台內交易",
)
# 安全語境成立時，這些訊號不應再被計入。
SUPPRESSED_WHEN_SAFE_SIGNALS = ("先匯款", "先匯", "私下交易")
SUPPRESSED_WHEN_SAFE_TERMS = ("先付", "訂金", "加 LINE", "連結")

HIGH_TERMS = (
    "金流驗證", "網路銀行", "ATM", "帳戶凍結", "OTP", "客服", "未認證",
    "解除分期", "分期設定錯誤", "保證獲利", "穩賺不賠", "老師帶單",
)
# 注意：貨到付款、代購、代儲本身是常見正常交易，不放入通用 MEDIUM_TERMS，
# 改由知識庫中與「沒訂過/拆封才發現/先給序號」等情境結合判斷，避免誤判。
MEDIUM_TERMS = ("先付", "訂金", "低價", "很多人", "不能面交", "加 LINE", "連結", "私人帳戶", "私人帳號", "繞過平台")

PSEUDO_PATTERNS: dict[str, tuple[str, ...]] = {
    "假買家詐騙": ("無法下單", "賣家未認證", "買家", "賣場違規"),
    "假客服金流驗證": ("金流驗證", "客服", "帳戶凍結", "網路銀行", "ATM"),
    "假物流或釣魚連結": ("賣貨便", "全家好賣", "蝦皮", "物流", "連結", "LINE"),
    "二手交易先匯款風險": ("先匯", "訂金", "保留", "私下交易"),
    "異常低價與急迫付款": ("低價", "便宜", "限時", "很多人", "今天"),
    "解除分期付款詐騙": ("解除分期", "分期設定錯誤", "重複扣款", "升級VIP", "經理代號"),
    "貨到付款換包裹詐騙": ("貨到付款", "代收貨款", "不明包裹", "沒訂過"),
    "假投資保證獲利": ("保證獲利", "穩賺", "老師帶單", "投資群組", "飆股", "出金"),
    "代購代儲遊戲交易": ("代購", "代儲", "點數卡", "遊戲幣", "寶物"),
}

# --- 評分常數 -------------------------------------------------------
SIGNAL_WEIGHT = 4  # RAG 命中一個 risk_signal 的加權
MIN_DISPLAY_TOKEN_HITS = 5  # 無 risk_signal 命中時，需達此 token 重疊才視為相關依據
HIGH_MATCH_THRESHOLD = 3  # 知識庫命中訊號達此數即視為高風險
SAFE_GUIDANCE_ID = "kb-006"  # 正常交易守則，低風險時作為唯一引用
HIGH_BASE_SCORE = 75
HIGH_SCORE_CAP = 95
MEDIUM_BASE_SCORE = 45
MEDIUM_SCORE_CAP = 74
LOW_SCORE = 20
PER_TERM_POINTS = 5  # 每個高/中風險詞的加分
PER_EVIDENCE_POINTS = 3  # 每個知識庫命中訊號的加分
MAX_EVIDENCE = 3

# --- 語意檢索（可選，bge-m3）常數 ---------------------------------
# 檢索（召回）用 HyDE 假想文件嵌入；軟提醒（判別）用原文嵌入。
SEMANTIC_WEIGHT = 10  # HyDE 語意相似度併入檢索排序的權重
SEM_RELEVANT = 0.55  # HyDE 檢索：純語意也納入引用依據的門檻（召回導向，偏寬）
# 軟提醒門檻：原文對「詐騙樣態 KB」的最高 cosine。
# 實測 bge-m3：新話術詐騙與正常交易在 0.65–0.68 重疊，無法據此可靠「升級風險等級」
# （正常購物會被誤升）。故僅作「不改變風險等級」的軟提醒＋保留相關引用，
# 真正的新話術等級判別交由 LLM 層。
SEM_ADVISORY = 0.66
SEMANTIC_SIGNAL = "語意上與已知詐騙樣態相似，建議提高警覺"

RISK_ORDER = {"低": 0, "中": 1, "高": 2}


@lru_cache(maxsize=1)
def load_knowledge_base() -> tuple[dict, ...]:
    """讀取並快取知識庫，避免每次分析重複讀檔。"""
    with KB_PATH.open("r", encoding="utf-8") as handle:
        return tuple(json.load(handle))


def load_test_cases() -> list[dict]:
    with TEST_CASES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# --- 語意檢索：KB 向量快取 + 相似度 --------------------------------
def _kb_texts() -> list[str]:
    return [
        f'{item["title"]} {item["guidance"]} {" ".join(item["risk_signals"])}'
        for item in load_knowledge_base()
    ]


def _kb_digest(texts: list[str]) -> str:
    hasher = hashlib.sha256()
    hasher.update(embeddings.EMBED_MODEL.encode("utf-8"))
    for text in texts:
        hasher.update(text.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


@lru_cache(maxsize=1)
def kb_vectors() -> tuple[tuple[float, ...], ...] | None:
    """回傳與 KB 對齊的嵌入向量；優先讀快取，無效則在 embedder 可用時重算。

    embedder 不可用（未拉 bge-m3 / 連不到）時回 None，由上層退回純詞彙檢索。
    """
    texts = _kb_texts()
    digest = _kb_digest(texts)
    try:
        with KB_EMBED_CACHE_PATH.open("r", encoding="utf-8") as handle:
            cached = json.load(handle)
        if cached.get("hash") == digest and len(cached.get("vectors", [])) == len(texts):
            return tuple(tuple(vec) for vec in cached["vectors"])
    except (OSError, ValueError):
        pass

    if not embeddings.is_available():
        return None
    vectors = embeddings.embed(texts)
    if not vectors or len(vectors) != len(texts):
        return None
    try:
        with KB_EMBED_CACHE_PATH.open("w", encoding="utf-8") as handle:
            json.dump({"model": embeddings.EMBED_MODEL, "hash": digest, "vectors": vectors}, handle)
    except OSError:
        pass  # 寫快取失敗（唯讀資料夾）不影響運作
    return tuple(tuple(vec) for vec in vectors)


def semantic_sims(text: str) -> list[float] | None:
    """檢索（召回）：以 HyDE 假想文件作為查詢向量，算對每筆 KB 的餘弦相似度。

    HyDE 文件在此「真的參與檢索」。embedder 或向量不可用時回 None。
    """
    vectors = kb_vectors()
    if not vectors:
        return None
    query = embeddings.embed_one(hyde_document(text))
    if not query:
        return None
    return [embeddings.cosine(query, vec) for vec in vectors]


def semantic_escalation_sim(text: str) -> float | None:
    """升級（判別）：以「原文」嵌入對詐騙樣態 KB（除安全守則）的最高 cosine。

    用原文而非 HyDE，避免 HyDE 模板把所有文字都拉向詐騙、無法判別。
    embedder 或向量不可用時回 None（→ 不升級、退回純詞彙）。
    """
    vectors = kb_vectors()
    if not vectors:
        return None
    query = embeddings.embed_one(text)
    if not query:
        return None
    kb = load_knowledge_base()
    sims = [embeddings.cosine(query, vectors[i]) for i, item in enumerate(kb) if item["id"] != SAFE_GUIDANCE_ID]
    return max(sims, default=0.0)


def is_safe_payment_context(prepared: PreparedText) -> bool:
    return any(phrase.lower() in prepared.normalized for phrase in SAFE_PAYMENT_PHRASES)


def pseudo_queries(prepared: PreparedText) -> list[str]:
    queries = [prepared.original.strip()]
    safe = is_safe_payment_context(prepared)
    for label, keys in PSEUDO_PATTERNS.items():
        if safe and label == "二手交易先匯款風險":
            continue
        if match_terms(list(keys), prepared):
            queries.append(label)
    return list(dict.fromkeys(queries))


def hyde_document(text: str) -> str:
    return (
        "這可能是一則二手交易詐騙案例：對方可能以交易異常、金流驗證、"
        "物流連結、私下加 LINE、先付訂金或操作 ATM/網銀等理由，誘導使用者"
        f"離開平台或提供付款資訊。原始描述：{text}"
    )


def _kb_signal_hits(item: dict, prepared: PreparedText, safe: bool) -> list[str]:
    hits = match_terms(list(item["risk_signals"]), prepared)
    if safe:
        hits = [signal for signal in hits if signal not in SUPPRESSED_WHEN_SAFE_SIGNALS]
    return hits


def retrieve_evidence(
    prepared: PreparedText, queries: list[str], sims: list[float] | None = None
) -> list[dict]:
    """混合檢索：詞彙重疊（bigram + risk_signal 加權）＋ 可選的語意相似度。

    sims 為 HyDE 查詢對每筆 KB 的餘弦相似度（與 KB 對齊）；None 時退回純詞彙。
    """
    safe = is_safe_payment_context(prepared)
    tokens = tokenize(prepared.normalized + " " + " ".join(queries))
    scored = []
    for index, item in enumerate(load_knowledge_base()):
        haystack = " ".join(
            [item["title"], item["guidance"], " ".join(item["risk_signals"])]
        )
        signal_hits = _kb_signal_hits(item, prepared, safe)
        token_hits = len(tokens & tokenize(haystack))
        sim = sims[index] if sims else 0.0
        # 語意夠相似時，即使零詞彙重疊也納入引用（讓新話術也找得到相關樣態）。
        relevant = bool(signal_hits) or token_hits >= MIN_DISPLAY_TOKEN_HITS or sim >= SEM_RELEVANT
        if not relevant:
            continue
        score = token_hits + len(signal_hits) * SIGNAL_WEIGHT + SEMANTIC_WEIGHT * sim
        scored.append(
            {**item, "score": score, "matched_signals": signal_hits, "semantic_sim": round(sim, 3)}
        )
    scored.sort(key=lambda entry: entry["score"], reverse=True)
    return scored[:MAX_EVIDENCE]


def _safe_guidance_citation() -> dict | None:
    for item in load_knowledge_base():
        if item["id"] == SAFE_GUIDANCE_ID:
            return {**item, "score": 0, "matched_signals": []}
    return None


def classify_risk(
    prepared: PreparedText, evidence: list[dict]
) -> tuple[str, int, list[str], list[str]]:
    """回傳 (等級, 分數, 高風險命中詞, 中風險命中詞)。"""
    safe = is_safe_payment_context(prepared)
    high_hits = match_terms(list(HIGH_TERMS), prepared)
    medium_hits = match_terms(list(MEDIUM_TERMS), prepared)
    if safe:
        high_hits = [t for t in high_hits if t not in SUPPRESSED_WHEN_SAFE_TERMS]
        medium_hits = [t for t in medium_hits if t not in SUPPRESSED_WHEN_SAFE_TERMS]
    matched_count = sum(len(item["matched_signals"]) for item in evidence)

    if high_hits or matched_count >= HIGH_MATCH_THRESHOLD:
        score = min(
            HIGH_SCORE_CAP,
            HIGH_BASE_SCORE + len(high_hits) * PER_TERM_POINTS + matched_count * PER_EVIDENCE_POINTS,
        )
        return "高", score, high_hits, medium_hits
    if medium_hits or (matched_count >= 1 and not safe):
        score = min(
            MEDIUM_SCORE_CAP,
            MEDIUM_BASE_SCORE + len(medium_hits) * PER_TERM_POINTS + matched_count * PER_EVIDENCE_POINTS,
        )
        return "中", score, [], medium_hits
    return "低", LOW_SCORE, [], []


def analyze_rules(text: str) -> dict:
    """純規則分析，輸出穩定鍵值供 orchestrator 與測試使用。"""
    prepared = prepare(text)
    queries = pseudo_queries(prepared)
    sims = semantic_sims(text)  # embedder 不可用時為 None → 純詞彙
    evidence = retrieve_evidence(prepared, queries, sims)
    level, score, high_hits, medium_hits = classify_risk(prepared, evidence)

    # 語意軟提醒（補新話術在規則層的能見度，但「不改變風險等級」）：
    # 低風險且非安全語境時，若「原文」語意接近已知詐騙樣態，加一條提醒並保留相關引用。
    # 註：實測 bge-m3 上正常交易與新話術詐騙相似度重疊，無法據此可靠升級等級，
    # 故只做軟提醒；等級判別交由 LLM 層。
    semantic_flag = False
    if level == "低" and not is_safe_payment_context(prepared):
        sim = semantic_escalation_sim(text)
        if sim is not None and sim >= SEM_ADVISORY:
            semantic_flag = True

    # 低風險且無任何詐騙訊號：無語意提醒時只引用「正常交易守則」避免誤導；
    # 有語意提醒時則保留語意檢索到的相關樣態當引用，讓使用者看到警示依據。
    if level == "低" and not semantic_flag and not any(item["matched_signals"] for item in evidence):
        guidance = _safe_guidance_citation()
        evidence = [guidance] if guidance else []

    signals = (high_hits + medium_hits) if level == "高" else medium_hits if level == "中" else []
    if semantic_flag and SEMANTIC_SIGNAL not in signals:
        signals.append(SEMANTIC_SIGNAL)
    evidence_signals = [sig for item in evidence for sig in item["matched_signals"]]
    highlights = highlight_spans(
        {"high": high_hits + evidence_signals, "medium": medium_hits}, text
    )
    return {
        "風險等級": level,
        "風險分數": score,
        "pseudo_queries": queries,
        "HyDE假想文件": hyde_document(text),
        "命中話術標註": highlights,
        "可疑訊號": signals or ["未偵測到明顯高風險話術"],
        "引用到的防詐依據": [
            {
                "id": item["id"],
                "title": item["title"],
                "matched_signals": item["matched_signals"],
                "source_url": item["source_url"],
                "語意相似": item.get("semantic_sim"),
            }
            for item in evidence
        ],
    }
