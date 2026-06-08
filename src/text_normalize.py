"""文字正規化與同義詞處理。

詐騙訊息常用全形字、插入標點、同義詞或注音來規避關鍵字偵測。
這個模組把原始文字轉成多種比對友善的表示法，並提供統一的
`contains` / `match_terms` 介面給規則引擎使用。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# 詐騙常見的「拆字規避」分隔符號：金．流．驗．證 / 加 L I N E。
# 比對 compact 版本時會把這些字元全部移除。
SEPARATOR_PATTERN = re.compile(
    r"[\s\.。．・·‧\-–—_/\\|~、​‌‍﻿]+"
)

# canonical 詞 -> 變體拼法。任一變體出現都視為 canonical 詞命中。
# 只放高精度、不易誤判的同義詞。
SYNONYMS: dict[str, tuple[str, ...]] = {
    "匯款": ("轉帳", "轉錢", "匯錢", "轉一筆"),
    "先匯款": ("先付款", "先轉帳", "先付訂", "先付訂金", "預付", "先打錢"),
    "LINE": ("賴", "加賴", "line id", "賴 id", "telegram", "tg"),
    "OTP": ("驗證碼", "一次性密碼", "簡訊碼", "動態密碼", "簡訊驗證碼"),
    "帳戶凍結": ("凍結", "解凍", "解除凍結", "帳號凍結", "帳戶異常", "帳號被鎖", "帳號異常"),
    "客服": ("客服人員", "官方客服", "專員", "小編", "在線客服"),
    "金流驗證": ("金流認證", "金流確認", "交易驗證", "認證金流", "啟用金流"),
    "網路銀行": ("網銀", "網路銀行app", "行動銀行", "手機銀行"),
    "面交": ("當面交易", "見面交易", "當面交付"),
    "解除分期": ("取消分期", "解除設定", "解除分期付款", "取消分期付款", "關閉分期"),
    "保證獲利": ("穩賺", "穩賺不賠", "穩定獲利", "保證賺", "包賺"),
}


def nfkc_lower(text: str) -> str:
    """NFKC 正規化（全形轉半形、相容字統一）後轉小寫。"""
    return unicodedata.normalize("NFKC", text).lower()


@dataclass(frozen=True)
class PreparedText:
    """同一段文字的多種比對表示法。"""

    original: str
    normalized: str  # NFKC + lower
    compact: str  # normalized 再移除分隔符號，用於對抗拆字規避


def prepare(text: str) -> PreparedText:
    normalized = nfkc_lower(text)
    compact = SEPARATOR_PATTERN.sub("", normalized)
    return PreparedText(original=text, normalized=normalized, compact=compact)


def _variants(term: str) -> tuple[str, ...]:
    return (term, *SYNONYMS.get(term, ()))


def contains(term: str, prepared: PreparedText) -> bool:
    """term（或其同義詞）是否出現在文字中，容忍全形與拆字規避。"""
    for variant in _variants(term):
        variant_norm = nfkc_lower(variant)
        if variant_norm in prepared.normalized:
            return True
        variant_compact = SEPARATOR_PATTERN.sub("", variant_norm)
        if variant_compact and variant_compact in prepared.compact:
            return True
    return False


def match_terms(terms: list[str], prepared: PreparedText) -> list[str]:
    """回傳 terms 中有命中的詞（保留原始寫法，供報告顯示）。"""
    return [term for term in terms if contains(term, prepared)]


# 高亮用：term 各字元之間允許插入分隔符號，才能在原文中找到
# 「金．流．驗．證」這類拆字規避的實際位置。
_SEP_BETWEEN = r"[\s\.。．・·‧\-–—_/\\|~、]*"


def find_spans(term: str, original: str) -> list[tuple[int, int]]:
    """在原文中找出 term（或其同義詞）的出現位置，容忍拆字規避。

    回傳 [(start, end), ...]，位移對應原始字串，供前端標註。
    """
    spans: list[tuple[int, int]] = []
    for variant in _variants(term):
        chars = [ch for ch in variant if not ch.isspace()]
        if not chars:
            continue
        pattern = _SEP_BETWEEN.join(re.escape(ch) for ch in chars)
        for match in re.finditer(pattern, original, re.IGNORECASE):
            if match.end() > match.start():
                spans.append((match.start(), match.end()))
    return spans


def highlight_spans(terms_by_level: dict[str, list[str]], original: str) -> list[dict]:
    """把多個等級的命中詞轉成不重疊、依位置排序的標註區間。

    terms_by_level 例：{"high": [...], "medium": [...]}；重疊時取較高等級。
    """
    rank = {"high": 2, "medium": 1}
    raw: list[tuple[int, int, str]] = []
    for level, terms in terms_by_level.items():
        for term in terms:
            for start, end in find_spans(term, original):
                raw.append((start, end, level))
    raw.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    merged: list[dict] = []
    for start, end, level in raw:
        if merged and start < merged[-1]["end"]:
            last = merged[-1]
            last["end"] = max(last["end"], end)
            if rank[level] > rank[last["level"]]:
                last["level"] = level
            continue
        merged.append({"start": start, "end": end, "level": level})
    return merged


def tokenize(text: str) -> set[str]:
    """斷詞並支援中文 bigram。

    連續中文以重疊 2-gram 切分，避免「金流驗證」整串變成單一 token
    導致 RAG token 重疊在中文上失效；英數則保留整詞。
    """
    lowered = nfkc_lower(text)
    tokens: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", lowered):
        tokens.add(word)
    for run in re.findall(r"[一-鿿]+", lowered):
        if len(run) == 1:
            tokens.add(run)
            continue
        for index in range(len(run) - 1):
            tokens.add(run[index : index + 2])
    return tokens
