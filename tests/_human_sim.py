"""模擬真人使用：20 個情境，每筆走 UI 實際的兩段式流程（?llm=0 即時 → 完整 LLM），
外加錯誤處理檢查。確認全程都能用、不崩、分級合理、快/慢一致。"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"
ORD = {"低": 0, "中": 1, "高": 2}

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass


def call(text, fast):
    url = f"{BASE}/api/analyze" + ("?llm=0" if fast else "")
    data = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status, json.loads(r.read().decode("utf-8")), time.time() - t0


# (情境名, 文字, 期望方向：'scam'=中或高 / 'safe'=低 / 'any'=只要能跑)
SCENARIOS = [
    ("經典假客服金流驗證", "買家說無法下單要我加LINE客服，客服說帳號未認證要操作網銀做金流驗證", "scam"),
    ("解除分期(165最常見)", "我是蝦皮客服，您分期設定錯誤每月會重複扣款，請到ATM操作解除分期", "scam"),
    ("拆字規避", "客服要我去網．路．銀．行做金．流．驗．證解除帳戶凍結", "scam"),
    ("全形+簡訊碼", "請到ＡＴＭ操作，把簡訊驗證碼給客服才能完成", "scam"),
    ("站外私下匯款", "平台手續費很貴，你直接匯到我帳戶我算你便宜，不用透過蝦皮", "scam"),
    ("假投資群組", "加入老師的投資群組，保證獲利穩賺不賠，飆股內線一週賺三成", "scam"),
    ("貨到付款換包裹", "我根本沒買過卻收到貨到付款包裹，付了錢拆開發現是空盒跟商品不符", "scam"),
    ("賣貨便親友詐騙", "我人在台東，我家人想跟你買可以幫忙開賣貨便嗎，我教你設定先加我賴", "scam"),
    ("代購先給序號", "幫代購遊戲點數卡，先給我序號我幫你代儲，便宜很多", "scam"),
    ("低價急迫先付訂金", "iPhone15只要8000，現在很多人問先付2000訂金才保留，不方便面交只能寄", "scam"),
    ("正常面交", "出售二手羅技滑鼠500，台北車站面交可現場測試，不接受先匯款", "safe"),
    ("正常蝦皮COD收到貨", "蝦皮下單選貨到付款，今天去全家取貨付款拿到手機殼，包裝完整", "safe"),
    ("純問候詢問", "你好，請問這個還在嗎？想約週末面交看看", "safe"),
    ("正常匯款詢問", "請問要怎麼付款？用蝦皮下單還是其他方式都可以", "safe"),
    ("emoji+簡訊風格", "在嗎😀 這個多少 可以面交嗎 我在板橋👍", "safe"),
    ("超短輸入", "還在嗎", "any"),
    ("貼到多餘空白換行", "  你好   \n\n 想買這個 \n 可以面交嗎  ", "safe"),
    ("中英混雜詐騙", "Hi 我buyer，下單fail了，加我line客服處理金流驗證ok?", "scam"),
    ("長段落對話貼上", "賣家你好我要買，可是一直顯示無法下單，截圖寫您訂購的賣場尚未簽署協議，"
     "客服說要我先匯一筆保證金開通金流協議，還傳了一個賣貨便連結叫我加LINE，這樣正常嗎", "scam"),
    ("錯字與口語", "欸這個我也要 但我比較想用轉帳的 可以給我妳的帳戶嗎 不想透過平台手續費太貴", "scam"),
]


def check_one(name, text, expect):
    issues = []
    # 1) 即時（規則）段
    s1, fast, t1 = call(text, True)
    if s1 != 200:
        return False, [f"fast HTTP {s1}"], t1, 0
    if fast.get("llm_used") is not False:
        issues.append("fast 應 llm_used=False")
    for key in ("風險等級", "風險分數", "可疑訊號", "引用到的防詐依據", "命中話術標註", "建議行動"):
        if key not in fast:
            issues.append(f"fast 缺欄位 {key}")

    # 2) 完整（含 LLM）段
    s2, full, t2 = call(text, False)
    if s2 != 200:
        return False, issues + [f"full HTTP {s2}"], t1, t2
    if not full.get("llm_used"):
        issues.append("full llm_used 應為 True（LLM 模式）")

    final = full["風險等級"]
    rules_lvl = full["規則研判"]["風險等級"]
    # 融合不得低於規則（取較高風險）
    if ORD[final] < ORD[rules_lvl]:
        issues.append(f"融合低於規則（{rules_lvl}→{final}）")

    # 方向性檢查
    if expect == "scam" and ORD[final] < 1:
        issues.append(f"詐騙情境卻判低（{final}）")
    if expect == "safe" and ORD[final] > 1:
        issues.append(f"正常情境卻判高（{final}）")

    ok = not issues
    tag = f"規則{rules_lvl}/LLM{full['LLM研判']['風險等級'] if full.get('LLM研判') else '-'}/最終{final}"
    return ok, issues or [tag], t1, t2


def main():
    print("=== 20 情境 × 兩段式（規則即時 + 完整 LLM）===\n")
    passed = 0
    total_fast = total_full = 0.0
    for i, (name, text, expect) in enumerate(SCENARIOS, 1):
        ok, info, t1, t2 = check_one(name, text, expect)
        total_fast += t1
        total_full += t2
        mark = "✓" if ok else "✗"
        passed += ok
        print(f"{mark} {i:2d}. [{name}] {info[0] if ok else '；'.join(info)}  (規則{t1*1000:.0f}ms / LLM{t2:.1f}s)")

    print(f"\n情境通過：{passed}/20")
    print(f"平均：規則 {total_fast/20*1000:.0f}ms、LLM {total_full/20:.1f}s")

    # === 錯誤處理 ===
    print("\n=== 錯誤處理（人為誤操作）===")
    err = 0
    cases = [
        ("空字串", {"text": ""}, 400),
        ("只有空白", {"text": "   "}, 400),
        ("缺 text 欄位", {"foo": "bar"}, 400),
    ]
    for name, payload, want in cases:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{BASE}/api/analyze", data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                got = r.status
        except urllib.error.HTTPError as e:
            got = e.code
        ok = got == want
        err += ok
        print(f"{'✓' if ok else '✗'} {name}: 期望 {want} 得到 {got}")

    # 超長文字
    data = json.dumps({"text": "詐" * 9000}).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/api/analyze", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            got = r.status
    except urllib.error.HTTPError as e:
        got = e.code
    ok = got == 400
    err += ok
    print(f"{'✓' if ok else '✗'} 超長文字(9000字): 期望 400 得到 {got}")

    print(f"\n錯誤處理通過：{err}/4")
    print(f"\n{'★ 全部可用' if passed == 20 and err == 4 else '⚠ 有項目未通過，見上方'}")


if __name__ == "__main__":
    main()
