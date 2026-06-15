"""詐騙攻擊鏈：判斷對話走到詐騙劇本的哪一階段，並預測對方下一步。

把「偵測」延伸成「看穿劇本」：二手交易詐騙通常照一條漏斗推進——
建立接觸 → 製造異常與急迫 → 誘導離開平台 → 金流操作收割。
完全離線、決定性，重用 text_normalize 的拆字規避/同義詞容忍比對。
"""

from __future__ import annotations

from text_normalize import PreparedText, match_terms

# 各階段的觸發詞（與 rules_engine 的詞表對齊；同義詞由 text_normalize 容忍）。
STAGE_PATTERNS: list[dict] = [
    {"id": 1, "name": "建立接觸", "terms": ()},  # baseline：有對話就算進入接觸
    {
        "id": 2,
        "name": "製造異常與急迫",
        "terms": (
            "無法下單", "賣家未認證", "未認證", "賣場違規", "帳戶凍結",
            "限時", "很多人", "今天", "低價", "便宜", "保證獲利", "穩賺",
        ),
    },
    {
        "id": 3,
        "name": "誘導離開平台",
        "terms": (
            "加 LINE", "LINE", "賣貨便", "全家好賣", "私下交易", "連結",
            "繞過平台", "私人帳號", "私人帳戶", "客服",
        ),
    },
    {
        "id": 4,
        "name": "金流操作／收割",
        "terms": (
            "金流驗證", "網路銀行", "ATM", "OTP", "解除分期", "分期設定錯誤",
            "先匯款", "匯款", "訂金", "升級VIP", "經理代號",
        ),
    },
]

# 安全語境（使用者主動拒絕/要求面交）成立時，這些「常被否定」的詞不計入階段，
# 避免「不接受先匯款」「不加 LINE」被誤判成已進入金流/離開平台階段。
SUPPRESS_WHEN_SAFE = frozenset(
    {"先匯款", "匯款", "訂金", "私下交易", "加 LINE", "LINE", "連結", "繞過平台"}
)

# 依「目前階段」預測對方下一步。
NEXT_PREDICTION = {
    1: "目前是一般接觸階段。若對方開始說「無法下單／需要驗證／限時優惠」製造異常，再提高警覺。",
    2: "對方下一步很可能要你「加 LINE／點他給的連結」把交易帶離平台。",
    3: "對方接下來可能要你「做金流驗證／到 ATM 或網銀操作／先匯訂金」。⚠️ 這是收割前一步，務必停下。",
    4: "已進入金流操作（收割）階段——這是詐騙的最後一步。立刻停止操作、不要提供 OTP／網銀帳密，並撥打 165 查證。",
}


def analyze_attack_chain(prepared: PreparedText, safe: bool = False) -> dict:
    """回傳攻擊鏈各階段命中情形、目前階段與下一步預測。

    safe=True（安全語境）時，抑制常被否定的金流/站外詞，避免誤判階段。
    """
    has_text = bool(prepared.normalized.strip())
    stages = []
    current = 1 if has_text else 0
    for stage in STAGE_PATTERNS:
        hits = match_terms(list(stage["terms"]), prepared) if stage["terms"] else []
        if safe:
            hits = [h for h in hits if h not in SUPPRESS_WHEN_SAFE]
        detected = bool(hits) or (stage["id"] == 1 and has_text)
        if detected:
            current = max(current, stage["id"])
        stages.append(
            {"id": stage["id"], "name": stage["name"], "detected": detected, "hits": hits}
        )
    return {
        "stages": stages,
        "current_stage": current,
        "next_prediction": NEXT_PREDICTION.get(current, NEXT_PREDICTION[1]),
    }
