"""安全回覆腳本：把「偵測」延伸成「主動應對」。

依風險等級與對話中命中的詐騙手法，組出使用者可以「直接貼回去」反測對方的
安全話術——堅持平台內交易、面交驗貨、拒絕站外付款與金流驗證。
完全離線、決定性，重用 text_normalize 的拆字規避/同義詞容忍比對。
"""

from __future__ import annotations

from text_normalize import PreparedText, match_terms

# 各手法類別的觸發詞（同義詞與拆字規避由 text_normalize 容忍）。
OFFSITE_TERMS = ["加 LINE", "LINE", "連結", "私下交易", "賣貨便", "全家好賣", "繞過平台"]
PAYMENT_TERMS = ["金流驗證", "網路銀行", "ATM", "OTP", "帳戶凍結", "解除分期", "升級VIP"]
DEPOSIT_TERMS = ["先匯款", "匯款", "訂金", "私人帳號", "私人帳戶"]

BASE_REPLY = "不好意思，我習慣全程在平台內交易並保留對話紀錄，方便的話想約面交當面驗貨，可以嗎？"
OFFSITE_REPLY = "我不方便加 LINE 或在站外付款喔，平台內的金流和客服才有保障；如果是正常交易應該沒問題吧？"
PAYMENT_REPLY = "正常的客服或銀行不會要我做金流驗證、或到 ATM／網路銀行操作；這部分我會直接打 165 確認後再回覆你。"
DEPOSIT_REPLY = "我不先付訂金，習慣面交或走平台的第三方金流，這樣對買賣雙方都比較安全。"
LOW_TIP = "交易前可先確認三件事：能否平台內交易、能否面交當面驗貨、保留完整對話紀錄，就能避開大多數風險。"


def build_safe_replies(level: str, prepared: PreparedText) -> list[str]:
    """回傳可直接貼回去的安全回覆話術；低風險給一句正向提醒，中/高給針對性話術。"""
    if level == "低":
        return [LOW_TIP]
    replies = [BASE_REPLY]
    if match_terms(OFFSITE_TERMS, prepared):
        replies.append(OFFSITE_REPLY)
    if match_terms(PAYMENT_TERMS, prepared):
        replies.append(PAYMENT_REPLY)
    if match_terms(DEPOSIT_TERMS, prepared):
        replies.append(DEPOSIT_REPLY)
    return list(dict.fromkeys(replies))  # 去重保序
