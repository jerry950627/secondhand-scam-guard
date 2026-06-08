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

from link_check import check_text  # noqa: E402
from llm_client import LlmConfig, LlmVerdict, is_available, run_llm  # noqa: E402
from rules_engine import (  # noqa: E402
    RISK_ORDER,
    TEST_CASES_PATH,
    analyze_rules,
    load_test_cases,
)

# LLM 抬升風險時，分數至少要到該等級的下限。
LEVEL_FLOOR_SCORE = {"低": 20, "中": 55, "高": 80}

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


def _fuse_levels(rules_level: str, llm: LlmVerdict | None) -> tuple[str, str]:
    """取較高風險。回傳 (最終等級, 一句話綜合說明)。"""
    if llm is None:
        return rules_level, f"離線規則模式：依規則與 RAG 依據研判為「{rules_level}風險」。"
    final = rules_level if RISK_ORDER[rules_level] >= RISK_ORDER[llm.level] else llm.level
    note = (
        f"規則引擎研判「{rules_level}」、4B LLM（{llm.model}）研判「{llm.level}」"
        f"（信心 {llm.confidence}）；保守起見綜合取較高風險「{final}」。"
    )
    if llm.evasion_detected:
        note += " LLM 偵測到疑似注音/拆字規避手法。"
    return final, note


def _fuse_score(rules_level: str, rules_score: int, final_level: str, llm: LlmVerdict | None) -> int:
    if final_level == rules_level:
        return rules_score
    return max(rules_score, LEVEL_FLOOR_SCORE[final_level])


def analyze(text: str, use_llm: bool | None = None) -> dict:
    rules = analyze_rules(text)
    rules_level = rules["風險等級"]
    rules_score = rules["風險分數"]

    should_use_llm = _LLM_AVAILABLE if use_llm is None else use_llm
    llm = run_llm(text, rules["引用到的防詐依據"], _LLM_CONFIG) if should_use_llm else None

    final_level, note = _fuse_levels(rules_level, llm)
    final_score = _fuse_score(rules_level, rules_score, final_level, llm)

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

    return {
        "輸入文字": text,
        "風險等級": final_level,
        "風險分數": final_score,
        "綜合說明": note,
        "連結與電話查核": link_result,
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
