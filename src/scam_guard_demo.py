"""二手交易 AI 防踩雷助理 — 主入口（orchestrator）。

流程：規則引擎（離線、可解釋、RAG 引用） + 可選 4B LLM 語意研判，
以「取較高風險」融合，永不因 LLM 不可用而崩潰。
對外輸出鍵值維持穩定，server.py / app.js 不需更動既有欄位。
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

# 讓本檔被 CLI 或 server.py 以獨立模組載入時，都能 import 同層模組。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from attack_chain import analyze_attack_chain  # noqa: E402
from link_check import check_text  # noqa: E402
from safe_reply import build_safe_replies  # noqa: E402
from text_normalize import prepare  # noqa: E402
from llm_client import (  # noqa: E402
    LlmConfig,
    LlmVerdict,
    gemini_config,
    is_available,
    run_llm,
    transcribe_images,
)
from rules_engine import (  # noqa: E402
    RISK_ORDER,
    TEST_CASES_PATH,
    analyze_rules,
    is_safe_payment_context,
    load_knowledge_base,
    load_test_cases,
)

# LLM 抬升風險時，分數落在該等級區間 [下限, 上限] 內，依信心線性取值。
LEVEL_FLOOR_SCORE = {"低": 20, "中": 55, "高": 80}
LEVEL_CAP_SCORE = {"低": 44, "中": 74, "高": 95}
CONF_ESCALATE = 60  # LLM 要把風險「升級」所需的最低信心；低於此維持規則研判（降低誤判）。

STATIC_ACTIONS = [
    "不要離開原交易平台進行付款或驗證。",
    "不要點私訊連結，不提供 OTP、網銀帳密或付款 QR Code。",
    "要求賣家提供可驗證的商品照片、平台內交易紀錄與面交/官方付款方式。",
    "若出現客服、金流驗證或帳戶凍結話術，立即停止並撥打 165 查證。",
]
STATIC_QUESTIONS = [
    "是否能在原平台完成交易並保留對話紀錄？",
    "是否能提供今天日期手寫紙條與商品同框照片？",
    "是否接受面交或平台內第三方金流？",
    "為什麼需要我加入 LINE 或操作銀行驗證？",
]

# 模組載入時偵測一次 LLM 是否可用，避免每次分析都探測。
_LLM_CONFIG = LlmConfig.from_env()
_LLM_AVAILABLE = is_available(_LLM_CONFIG)


def _warm_up_llm() -> None:
    """背景預熱：先載入模型到記憶體，讓第一個真實請求不必承受冷啟動。"""
    try:
        run_llm("測試", [], _LLM_CONFIG)
    except Exception:
        pass


if _LLM_AVAILABLE:
    threading.Thread(target=_warm_up_llm, daemon=True).start()


def _select_llm(mode: str, gemini_api_key: str) -> tuple[LlmConfig | None, bool]:
    """依模式選 LLM 設定。回傳 (設定, 該模式是否有可用 LLM)。

    online：用每次請求帶入的 Gemini key 動態建設定（key 為空則無 LLM）。
    offline：沿用模組載入時偵測的本機設定與可用性。
    """
    if mode == "online":
        key = (gemini_api_key or "").strip()
        return (gemini_config(key), True) if key else (None, False)
    return _LLM_CONFIG, _LLM_AVAILABLE


def _fuse_levels(rules_level: str, llm: LlmVerdict | None) -> tuple[str, str]:
    """信心加權融合：LLM 只在信心足夠時才升級，且永不降級。回 (最終等級, 說明)。"""
    if llm is None:
        return rules_level, f"離線規則模式：依規則與 RAG 依據研判為「{rules_level}風險」。"
    llm_higher = RISK_ORDER[llm.level] > RISK_ORDER[rules_level]
    if llm_higher and llm.confidence >= CONF_ESCALATE:
        final = llm.level
        note = (
            f"規則研判「{rules_level}」、LLM（{llm.model}）研判「{llm.level}」"
            f"（信心 {llm.confidence} ≥ {CONF_ESCALATE}）；升級為「{final}」。"
        )
    elif llm_higher:
        final = rules_level
        note = (
            f"規則研判「{rules_level}」、LLM（{llm.model}）認為更高「{llm.level}」"
            f"但信心不足（{llm.confidence} < {CONF_ESCALATE}），維持規則研判「{final}」。"
        )
    else:
        final = rules_level  # 永不降級（防詐保守）
        note = (
            f"規則研判「{rules_level}」、LLM（{llm.model}）研判「{llm.level}」"
            f"（信心 {llm.confidence}）；維持較保守的「{final}」。"
        )
    if llm.evasion_detected:
        note += " LLM 偵測到疑似注音/拆字規避手法。"
    return final, note


def _fuse_score(rules_level: str, rules_score: int, final_level: str, llm: LlmVerdict | None) -> int:
    if final_level == rules_level:
        return rules_score
    # 升級時分數在該等級區間內隨 LLM 信心線性取值（信心加權的啟發式風險指標，非機率）。
    floor = LEVEL_FLOOR_SCORE[final_level]
    cap = LEVEL_CAP_SCORE.get(final_level, floor)
    confidence = max(0, min(100, llm.confidence)) if llm else 0
    scaled = floor + int((cap - floor) * confidence / 100)
    return max(rules_score, scaled)


def analyze(
    text: str,
    use_llm: bool | None = None,
    mode: str = "offline",
    gemini_api_key: str = "",
) -> dict:
    rules = analyze_rules(text)
    rules_level = rules["風險等級"]
    rules_score = rules["風險分數"]

    config, provider_available = _select_llm(mode, gemini_api_key)
    should_use_llm = provider_available if use_llm is None else (use_llm and config is not None)
    llm = run_llm(text, rules["引用到的防詐依據"], config) if should_use_llm else None

    final_level, note = _fuse_levels(rules_level, llm)
    final_score = _fuse_score(rules_level, rules_score, final_level, llm)

    # 線上版叫了 Gemini 卻拿不到結果（金鑰無效/逾時/格式錯誤）→ 明確告知已退回規則。
    if mode == "online" and should_use_llm and llm is None:
        note = f"線上 Gemini 研判失敗或金鑰無效，已退回規則依據研判為「{final_level}風險」。"

    # 黑名單比對：抽出網址/電話查核，若風險更高則保守提升最終等級。
    link_result = check_text(text)
    link_level = link_result["整體連結電話風險"]
    if link_level in RISK_ORDER and RISK_ORDER[link_level] > RISK_ORDER[final_level]:
        final_score = max(final_score, LEVEL_FLOOR_SCORE[link_level])
        final_level = link_level
        note += f" 另偵測到高風險連結/電話，綜合提升為「{final_level}」。"

    signals = list(rules["可疑訊號"])
    if llm and llm.evasion_detected and "疑似規避偵測手法" not in signals:
        signals.append("疑似規避偵測手法")

    # 防詐副駕：攻擊鏈階段＋下一步預測、可直接貼回去的安全回覆腳本（離線、決定性）。
    prepared = prepare(text)
    safe_context = is_safe_payment_context(prepared)
    attack_chain = analyze_attack_chain(prepared, safe=safe_context)
    safe_replies = build_safe_replies(final_level, prepared)

    return {
        "輸入文字": text,
        "風險等級": final_level,
        "風險分數": final_score,
        "綜合說明": note,
        "連結與電話查核": link_result,
        "攻擊鏈": attack_chain,
        "安全回覆建議": safe_replies,
        "分析模式": mode,
        "llm_used": llm is not None,
        "規則研判": {"風險等級": rules_level, "風險分數": rules_score},
        "LLM研判": (
            {
                "風險等級": llm.level,
                "信心": llm.confidence,
                "規避偵測": llm.evasion_detected,
                "理由": llm.reasons,
                "結論": llm.summary,
                "模型": llm.model,
            }
            if llm
            else None
        ),
        "pseudo_queries": rules["pseudo_queries"],
        "HyDE假想文件": rules["HyDE假想文件"],
        "命中話術標註": rules["命中話術標註"],
        "可疑訊號": signals,
        "引用到的防詐依據": rules["引用到的防詐依據"],
        "建議行動": list(STATIC_ACTIONS),
        "可問賣家的查證問題": list(STATIC_QUESTIONS),
    }


def knowledge_base() -> list[dict]:
    """回傳防詐知識庫全部樣態（供前端「詐騙樣態圖鑑」瀏覽）。"""
    return list(load_knowledge_base())


def vlm_transcribe(images, gemini_api_key: str) -> str | None:
    """線上版 VLM 入口：把一或多張截圖交給 Gemini 逐字轉錄。失敗回 None。

    images 可為單一 data URL 字串或 data URL 字串列表。
    """
    urls = [images] if isinstance(images, str) else list(images or [])
    return transcribe_images(urls, gemini_api_key)


def run_tests() -> list[dict]:
    """以純規則模式（決定性）驗證分級，與 LLM 是否在線無關。"""
    results = []
    for case in load_test_cases():
        output = analyze(case["input_text"], use_llm=False)
        passed = output["風險等級"] == case["expected_level"]
        results.append(
            {
                "id": case["id"],
                "expected": case["expected_level"],
                "actual": output["風險等級"],
                "passed": passed,
            }
        )
    return results


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        results = run_tests()
        print(json.dumps(results, ensure_ascii=False, indent=2))
        if not all(item["passed"] for item in results):
            raise SystemExit(1)
        return

    text = " ".join(sys.argv[1:]).strip()
    if not text:
        text = "買家說無法下單，要求我加 LINE 客服，客服說賣家未完成金流驗證，要點賣貨便連結並操作網路銀行。"
    print(json.dumps(analyze(text), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
