"""可選的 4B LLM 研判層（Ollama / OpenAI 相容），僅用標準庫。

設計原則：永不讓主流程崩潰。連不到模型、逾時或回傳格式錯誤時，
一律回傳 None，由 orchestrator 退回純規則模式。

環境變數：
  SCAM_LLM_ENABLED   auto(預設) | 1/true 強制 | 0/false 關閉
  SCAM_LLM_API       ollama(預設) | openai | gemini
  SCAM_LLM_BASE_URL  預設 http://localhost:11434
  SCAM_LLM_MODEL     預設 gemma3:4b
  SCAM_LLM_API_KEY   openai 相容端點用
  SCAM_LLM_TIMEOUT   秒，預設 30

線上版（Gemini）以每次請求帶入的 API key 動態建立設定，不經環境變數，
詳見 gemini_config()。Gemini 採 OpenAI 相容端點，但路徑少一段 /v1。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

VALID_LEVELS = {"低", "中", "高"}

SYSTEM_PROMPT = (
    "你是台灣二手交易（FB Marketplace、蝦皮、Threads）的防詐風險分析助理。"
    "依據使用者提供的交易對話或貼文，研判是否為詐騙，特別注意假買家、假客服、"
    "金流驗證、帳戶凍結、釣魚物流連結、私下加 LINE、先匯訂金、異常低價與急迫話術，"
    "以及刻意用注音、拆字、錯字規避偵測的手法。"
    "只輸出 JSON，不要任何其他文字。"
)

USER_TEMPLATE = (
    "交易內容：\n{text}\n\n"
    "已檢索到的防詐依據（供參考，可能為空）：\n{evidence}\n\n"
    "請輸出 JSON，欄位如下：\n"
    "{{\n"
    '  "risk_level": "低" 或 "中" 或 "高",\n'
    '  "confidence": 0 到 100 的整數,\n'
    '  "evasion_detected": true 或 false（是否用注音/拆字/錯字規避）,\n'
    '  "reasons": ["判斷理由，最多3條，每條一句話"],\n'
    '  "summary": "一句話結論"\n'
    "}}"
)


@dataclass(frozen=True)
class LlmConfig:
    enabled_mode: str
    api: str
    base_url: str
    model: str
    api_key: str
    timeout: float

    @classmethod
    def from_env(cls) -> "LlmConfig":
        return cls(
            enabled_mode=os.environ.get("SCAM_LLM_ENABLED", "auto").strip().lower(),
            api=os.environ.get("SCAM_LLM_API", "ollama").strip().lower(),
            base_url=os.environ.get("SCAM_LLM_BASE_URL", "http://localhost:11434").rstrip("/"),
            model=os.environ.get("SCAM_LLM_MODEL", "gemma3:4b").strip(),
            api_key=os.environ.get("SCAM_LLM_API_KEY", "").strip(),
            timeout=float(os.environ.get("SCAM_LLM_TIMEOUT", "60")),
        )


# 線上版：Gemini OpenAI 相容端點（注意路徑是 .../openai/chat/completions，少一段 /v1）。
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
# 用 2.5 Flash：免費層仍有額度；gemini-2.0-flash 免費層已為 0（會回 429）。
GEMINI_MODEL = "gemini-2.5-flash"

# VLM 轉錄用 system 指令：把截圖逐字轉文字，並附一行視覺詐騙線索觀察。
VLM_SYSTEM_PROMPT = (
    "你是台灣二手交易的截圖判讀助理。請把圖片中的交易對話或貼文「逐字」轉成純文字，"
    "保留原始用字（含注音、拆字、錯字，不要替使用者修正或美化），不要加入聊天框 UI、"
    "時間戳、按讚留言分享等介面雜訊。若圖片中出現假金流頁、釣魚物流通知、仿冒平台登入頁、"
    "偽造匯款證明等視覺線索，請在結尾用一行『（VLM 觀察：…）』簡述。只輸出轉錄文字與該行附註。"
)


def gemini_config(api_key: str, timeout: float = 60.0) -> "LlmConfig":
    """以每次請求帶入的 key 動態建立 Gemini（線上版）設定；key 不落地。"""
    return LlmConfig(
        enabled_mode="1",
        api="gemini",
        base_url=GEMINI_BASE_URL,
        model=GEMINI_MODEL,
        api_key=api_key.strip(),
        timeout=timeout,
    )


@dataclass(frozen=True)
class LlmVerdict:
    level: str
    confidence: int
    evasion_detected: bool
    reasons: list[str]
    summary: str
    model: str


def _http_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_json(content: str) -> dict | None:
    """從模型輸出中抽出第一個 JSON 物件（4B 模型有時會夾雜文字）。"""
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _normalize_level(raw: object) -> str | None:
    text = str(raw).strip()
    # 依風險高→低判斷，模型回傳含多個等級字（如「中高」）時保守取較高，
    # 且結果不依賴 set 迭代順序。
    for level in ("高", "中", "低"):
        if level in text:
            return level
    mapping = {"low": "低", "medium": "中", "mid": "中", "high": "高"}
    return mapping.get(text.lower())


def _to_verdict(parsed: dict, model: str) -> LlmVerdict | None:
    level = _normalize_level(parsed.get("risk_level"))
    if level is None:
        return None
    try:
        confidence = int(float(parsed.get("confidence", 0)))
    except (TypeError, ValueError):
        confidence = 0
    reasons_raw = parsed.get("reasons") or []
    if isinstance(reasons_raw, str):
        reasons_raw = [reasons_raw]
    reasons = [str(item).strip() for item in reasons_raw if str(item).strip()][:3]
    return LlmVerdict(
        level=level,
        confidence=max(0, min(100, confidence)),
        evasion_detected=bool(parsed.get("evasion_detected", False)),
        reasons=reasons,
        summary=str(parsed.get("summary", "")).strip(),
        model=model,
    )


def _build_user_prompt(text: str, evidence: list[dict]) -> str:
    if evidence:
        lines = [f"- {item['title']}：{item.get('matched_signals') or '語意相近'}" for item in evidence]
        evidence_text = "\n".join(lines)
    else:
        evidence_text = "（無）"
    return USER_TEMPLATE.format(text=text, evidence=evidence_text)


def _call_ollama(config: LlmConfig, prompt: str) -> str:
    payload = {
        "model": config.model,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    result = _http_json(
        f"{config.base_url}/api/chat",
        payload,
        {"Content-Type": "application/json"},
        config.timeout,
    )
    return result.get("message", {}).get("content", "")


def _extract_choice_content(result: dict) -> str:
    # 安全取值：端點回傳畸形（choices 為空/None、缺 message）時回空字串，
    # 交由上層 _extract_json 判為 None 並退回規則模式，不讓主流程崩潰。
    choices = result.get("choices") or []
    if not choices:
        return ""
    return (choices[0] or {}).get("message", {}).get("content", "")


def _post_chat_completions(config: LlmConfig, prompt: str, url: str) -> str:
    """OpenAI 相容 /chat/completions 呼叫（openai 與 gemini 共用，只差 url）。"""
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    payload = {
        "model": config.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    return _extract_choice_content(_http_json(url, payload, headers, config.timeout))


def _call_openai(config: LlmConfig, prompt: str) -> str:
    return _post_chat_completions(config, prompt, f"{config.base_url}/v1/chat/completions")


def _call_gemini(config: LlmConfig, prompt: str) -> str:
    # Gemini 的 OpenAI 相容路徑少一段 /v1：.../v1beta/openai/chat/completions。
    return _post_chat_completions(config, prompt, f"{config.base_url}/chat/completions")


def is_available(config: LlmConfig | None = None) -> bool:
    config = config or LlmConfig.from_env()
    if config.enabled_mode in {"0", "false", "off", "no"}:
        return False
    probe_url = (
        f"{config.base_url}/api/tags"
        if config.api == "ollama"
        else f"{config.base_url}/v1/models"
    )
    try:
        request = urllib.request.Request(probe_url, method="GET")
        if config.api_key:
            request.add_header("Authorization", f"Bearer {config.api_key}")
        with urllib.request.urlopen(request, timeout=3):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return config.enabled_mode in {"1", "true", "on", "yes"}


def run_llm(text: str, evidence: list[dict], config: LlmConfig | None = None) -> LlmVerdict | None:
    """呼叫 LLM 研判。任何失敗都回傳 None，由上層退回規則模式。

    對暫時性失敗（逾時、連線中斷、輸出非 JSON）重試一次，降低偶發 None。
    """
    config = config or LlmConfig.from_env()
    if config.enabled_mode in {"0", "false", "off", "no"}:
        return None
    prompt = _build_user_prompt(text, evidence)
    for attempt in range(2):
        try:
            if config.api == "ollama":
                content = _call_ollama(config, prompt)
            elif config.api == "gemini":
                content = _call_gemini(config, prompt)
            else:
                content = _call_openai(config, prompt)
        except (urllib.error.URLError, OSError, KeyError, IndexError, TypeError, ValueError, TimeoutError):
            continue
        parsed = _extract_json(content or "")
        if parsed is None:
            continue
        verdict = _to_verdict(parsed, config.model)
        if verdict is not None:
            return verdict
    return None


def transcribe_image(image_data_url: str, api_key: str, timeout: float = 60.0) -> str | None:
    """線上版 VLM：把截圖丟 Gemini 多模態，回傳逐字轉錄文字（含視覺線索附註）。

    任何失敗都回 None，由上層改用本機 OCR 或提示重試，不讓主流程崩潰。
    """
    key = (api_key or "").strip()
    if not key or not image_data_url:
        return None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    payload = {
        "model": GEMINI_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": VLM_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "請逐字轉錄這張二手交易截圖中的對話/貼文。"},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ],
    }
    try:
        result = _http_json(
            f"{GEMINI_BASE_URL}/chat/completions", payload, headers, timeout
        )
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    content = _extract_choice_content(result).strip()
    return content or None
