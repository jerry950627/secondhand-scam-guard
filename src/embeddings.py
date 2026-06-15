"""可選的本機語意嵌入層（Ollama，預設 bge-m3），僅用標準庫。

讓 RAG 從「詞彙重疊」升級為「詞彙 + 語意」混合檢索，並讓 HyDE 假想文件
真的參與檢索（以其嵌入向量做查詢）。

設計原則同 llm_client：永不讓主流程崩潰。模型未拉、連不到或格式錯誤時，
一律回傳 None / False，由 rules_engine 退回純詞彙檢索。

環境變數：
  SCAM_EMBED_MODEL     預設 bge-m3
  SCAM_LLM_BASE_URL    沿用 LLM 的 Ollama 位址，預設 http://localhost:11434
  SCAM_EMBED_TIMEOUT   秒，預設 20
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from functools import lru_cache

EMBED_MODEL = os.environ.get("SCAM_EMBED_MODEL", "bge-m3").strip()
BASE_URL = os.environ.get("SCAM_LLM_BASE_URL", "http://localhost:11434").rstrip("/")
TIMEOUT = float(os.environ.get("SCAM_EMBED_TIMEOUT", "20"))


def _http_json(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def embed(texts: list[str]) -> list[list[float]] | None:
    """把多段文字轉成向量。任何失敗都回 None（交由上層退回詞彙檢索）。"""
    cleaned = [str(t) for t in (texts or []) if str(t).strip()]
    if not cleaned:
        return None
    try:
        result = _http_json(
            f"{BASE_URL}/api/embed",
            {"model": EMBED_MODEL, "input": cleaned},
            TIMEOUT,
        )
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    vectors = result.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(cleaned):
        return None
    if not all(isinstance(v, list) and v for v in vectors):
        return None
    return vectors


@lru_cache(maxsize=256)
def embed_one(text: str) -> tuple[float, ...] | None:
    """單段文字嵌入（快取；兩段式分析對同一文字只算一次）。回 tuple 以便快取。"""
    vectors = embed([text])
    if not vectors:
        return None
    return tuple(vectors[0])


@lru_cache(maxsize=1)
def is_available() -> bool:
    """偵測 Ollama 是否在線且已拉 EMBED_MODEL（結果快取一次）。"""
    try:
        request = urllib.request.Request(f"{BASE_URL}/api/tags", method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    base = EMBED_MODEL.split(":", 1)[0]
    for model in data.get("models", []):
        name = str(model.get("name", ""))
        if name == EMBED_MODEL or name.split(":", 1)[0] == base:
            return True
    return False


def cosine(a, b) -> float:
    """餘弦相似度（純 Python）。長度不符或零向量回 0.0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
