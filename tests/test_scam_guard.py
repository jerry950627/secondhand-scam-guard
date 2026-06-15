"""二手交易防詐助理單元 / 整合測試。

執行：
    python -m pytest tests/ -v
不需任何外部套件以外的相依；LLM 相關測試以 monkeypatch 模擬，
不會真的連線到模型。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import link_check  # noqa: E402
import llm_client  # noqa: E402
import scam_guard_demo as demo  # noqa: E402
from rules_engine import analyze_rules, load_test_cases  # noqa: E402
from text_normalize import contains, find_spans, highlight_spans, prepare, tokenize  # noqa: E402


# --- text_normalize -------------------------------------------------
@pytest.mark.unit
def test_fullwidth_is_normalized():
    prepared = prepare("ＡＴＭ 操作")
    assert contains("ATM", prepared)


@pytest.mark.unit
def test_split_evasion_is_caught():
    prepared = prepare("金．流．驗．證")
    assert contains("金流驗證", prepared)


@pytest.mark.unit
def test_synonym_matches_canonical():
    assert contains("匯款", prepare("請先轉帳給我"))
    assert contains("LINE", prepare("加賴聊"))
    assert contains("OTP", prepare("把簡訊驗證碼給我"))


@pytest.mark.unit
def test_cjk_bigram_overlap():
    # 連續中文需以 bigram 切分才能在 RAG 重疊
    assert "金流" in tokenize("做金流驗證")
    assert tokenize("金流驗證") & tokenize("這是金流驗證的步驟")


# --- rules_engine ---------------------------------------------------
@pytest.mark.unit
@pytest.mark.parametrize("case", load_test_cases(), ids=lambda c: c["id"])
def test_rules_expected_levels(case):
    result = analyze_rules(case["input_text"])
    assert result["風險等級"] == case["expected_level"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected",
    [
        ("蝦皮客服說分期設定錯誤被重複扣款，請操作ATM解除分期", "高"),
        ("我沒訂過卻收到包裹，拆封才發現是空盒，與商品不符", "高"),
        ("加入老師的投資群組，保證獲利穩賺不賠", "高"),
        ("蝦皮下單選貨到付款，今天超商取貨付款拿到商品，正常", "低"),
    ],
)
def test_new_scam_types_and_legit_cod(text, expected):
    assert analyze_rules(text)["風險等級"] == expected


@pytest.mark.unit
def test_highlight_finds_split_evasion_span():
    spans = find_spans("金流驗證", "請做金．流．驗．證")
    assert spans, "拆字規避的話術也要能標出原文位置"
    start, end = spans[0]
    assert "金" in "請做金．流．驗．證"[start:end]
    assert "證" in "請做金．流．驗．證"[start:end]


@pytest.mark.unit
def test_highlight_merges_and_levels():
    original = "操作ATM做金流驗證"
    marks = highlight_spans({"high": ["ATM", "金流驗證"], "medium": []}, original)
    assert marks
    assert all(m["start"] < m["end"] for m in marks)
    assert all(m["level"] == "high" for m in marks)
    # 不重疊
    for prev, curr in zip(marks, marks[1:]):
        assert prev["end"] <= curr["start"]


@pytest.mark.unit
def test_analyze_emits_highlights_for_scam():
    result = analyze_rules("客服要我操作網路銀行做金流驗證")
    assert result["命中話術標註"], "高風險輸入應有命中話術標註"


@pytest.mark.unit
def test_safe_context_suppresses_false_positive():
    result = analyze_rules("二手鍵盤面交，可現場測試，不接受先匯款。")
    assert result["風險等級"] == "低"


@pytest.mark.unit
def test_evidence_has_citation_for_scam():
    result = analyze_rules("客服要我做金流驗證並操作網路銀行解除帳戶凍結")
    assert result["引用到的防詐依據"], "高風險案例應附 RAG 引用依據"
    assert all("source_url" in item for item in result["引用到的防詐依據"])


# --- orchestrator fusion -------------------------------------------
@pytest.mark.unit
def test_analyze_without_llm_keeps_rules_level():
    result = demo.analyze("一般面交，不接受先匯款", use_llm=False)
    assert result["llm_used"] is False
    assert result["LLM研判"] is None
    assert result["風險等級"] == "低"


@pytest.mark.integration
def test_fusion_takes_higher_risk(monkeypatch):
    verdict = llm_client.LlmVerdict(
        level="高",
        confidence=88,
        evasion_detected=True,
        reasons=["疑似假客服話術"],
        summary="高風險",
        model="gemma3:4b",
    )
    monkeypatch.setattr(demo, "run_llm", lambda *a, **k: verdict)
    # 規則只會判低的中性句，LLM 判高，融合後應為高
    result = demo.analyze("這個還在嗎想買", use_llm=True)
    assert result["llm_used"] is True
    assert result["風險等級"] == "高"
    assert result["風險分數"] >= 80
    assert "疑似規避偵測手法" in result["可疑訊號"]


@pytest.mark.integration
def test_fusion_never_downgrades_rules_high(monkeypatch):
    verdict = llm_client.LlmVerdict(
        level="低",
        confidence=10,
        evasion_detected=False,
        reasons=[],
        summary="看起來還好",
        model="gemma3:4b",
    )
    monkeypatch.setattr(demo, "run_llm", lambda *a, **k: verdict)
    high_text = "客服要我做金流驗證並操作網路銀行解除帳戶凍結"
    result = demo.analyze(high_text, use_llm=True)
    assert result["風險等級"] == "高"  # 保守：不因 LLM 低估而降級


@pytest.mark.integration
def test_llm_failure_falls_back_to_rules(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(llm_client, "_call_ollama", boom)
    config = llm_client.LlmConfig.from_env()
    assert llm_client.run_llm("測試", [], config) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected_level",
    [
        ("點 http://shopee-tw.xyz/pay 更新付款", "高"),  # 冒用品牌
        ("登入 http://192.168.0.5/login", "高"),  # 原始 IP
        ("到 https://reurl.cc/abc 領取", "中"),  # 短網址
        ("正常蝦皮 https://shopee.tw/p/1", "低"),  # 官方
        ("境外客服 +8613800138000 來電", "高"),  # 境外電話
        ("一般面交沒有連結也沒電話", "無"),  # 無
    ],
)
def test_link_check_levels(text, expected_level):
    assert link_check.check_text(text)["整體連結電話風險"] == expected_level


@pytest.mark.unit
def test_blocklist_domain_hit_is_reported():
    # blocklist.json 內的示範網域應命中黑名單（優先於啟發式）
    result = link_check.check_text("到 https://shopee-pay.top/login 付款")
    item = result["項目"][0]
    assert item["風險"] == "高"
    assert "黑名單" in item["原因"]


@pytest.mark.unit
def test_blocklist_phone_hit_normalized():
    # 886900111222 ＝ 0900111222，0 開頭也要命中
    result = link_check.check_text("打給我 0900111222")
    assert result["項目"][0]["風險"] == "高"
    assert "黑名單" in result["項目"][0]["原因"]


@pytest.mark.unit
def test_non_blocklisted_impersonation_uses_heuristic():
    result = link_check.check_text("點 http://momo-pay.xyz/go")
    item = result["項目"][0]
    assert item["風險"] == "高"
    assert "黑名單" not in item["原因"]  # 走啟發式而非黑名單


@pytest.mark.unit
def test_link_check_no_false_match_on_prices():
    result = link_check.check_text("NT$2500 賣，訂金 1000，共 5 件")
    assert result["項目"] == []


@pytest.mark.integration
def test_analyze_escalates_on_malicious_url():
    # 文字本身中性，但含冒用釣魚連結 → 最終應被提升為高
    result = demo.analyze("你好可以面交嗎，先點 http://shopee-tw.xyz/pay 驗證", use_llm=False)
    assert result["風險等級"] == "高"
    assert result["連結與電話查核"]["整體連結電話風險"] == "高"


@pytest.mark.unit
def test_llm_lenient_json_extraction():
    parsed = llm_client._extract_json('文字前綴 {"risk_level":"高","confidence":90} 後綴')
    assert parsed is not None
    verdict = llm_client._to_verdict(parsed, "gemma3:4b")
    assert verdict.level == "高"


# --- 離線/線上模式 + Gemini + VLM -----------------------------------
@pytest.mark.unit
def test_gemini_config_fields():
    config = llm_client.gemini_config("abc")
    assert config.api == "gemini"
    assert config.model == llm_client.GEMINI_MODEL
    assert config.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert config.enabled_mode == "1"
    assert config.api_key == "abc"


@pytest.mark.unit
def test_gemini_path_drops_v1_segment(monkeypatch):
    # Gemini 的 OpenAI 相容路徑是 .../openai/chat/completions（沒有 /v1）。
    captured = {}

    def fake_http(url, payload, headers, timeout):
        captured["url"] = url
        return {"choices": [{"message": {"content": '{"risk_level":"高","confidence":90}'}}]}

    monkeypatch.setattr(llm_client, "_http_json", fake_http)
    verdict = llm_client.run_llm("測試", [], llm_client.gemini_config("k"))
    assert verdict is not None and verdict.level == "高"
    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert "/v1/chat/completions" not in captured["url"]


@pytest.mark.unit
def test_select_llm_offline_uses_local_config():
    config, available = demo._select_llm("offline", "")
    assert config is demo._LLM_CONFIG
    assert available == demo._LLM_AVAILABLE


@pytest.mark.unit
def test_select_llm_online_with_key_builds_gemini():
    config, available = demo._select_llm("online", "  my-key  ")
    assert available is True
    assert config is not None
    assert config.api == "gemini"
    assert config.model == llm_client.GEMINI_MODEL
    assert config.base_url == llm_client.GEMINI_BASE_URL
    assert config.api_key == "my-key"


@pytest.mark.unit
def test_select_llm_online_without_key_disables_llm():
    config, available = demo._select_llm("online", "   ")
    assert config is None
    assert available is False


@pytest.mark.integration
def test_analyze_online_mode_tags_mode_and_model(monkeypatch):
    verdict = llm_client.LlmVerdict("高", 90, False, ["理由"], "結論", "gemini-2.5-flash")
    monkeypatch.setattr(demo, "run_llm", lambda text, evidence, config: verdict)
    result = demo.analyze("這個還在嗎想買", use_llm=True, mode="online", gemini_api_key="k")
    assert result["分析模式"] == "online"
    assert result["llm_used"] is True
    assert result["LLM研判"]["模型"] == "gemini-2.5-flash"


@pytest.mark.integration
def test_analyze_online_without_key_skips_llm(monkeypatch):
    def must_not_call(*args, **kwargs):
        pytest.fail("線上版無金鑰時不應呼叫 LLM")

    monkeypatch.setattr(demo, "run_llm", must_not_call)
    result = demo.analyze("一般面交，不接受先匯款", use_llm=True, mode="online", gemini_api_key="")
    assert result["llm_used"] is False
    assert result["分析模式"] == "online"


@pytest.mark.integration
def test_analyze_online_failure_notes_fallback(monkeypatch):
    monkeypatch.setattr(demo, "run_llm", lambda *a, **k: None)
    result = demo.analyze("一般面交，不接受先匯款", use_llm=True, mode="online", gemini_api_key="bad-key")
    assert result["llm_used"] is False
    assert "退回規則" in result["綜合說明"]


@pytest.mark.unit
def test_transcribe_image_empty_key_returns_none():
    assert llm_client.transcribe_image("data:image/png;base64,AAAA", "") is None


@pytest.mark.unit
def test_transcribe_image_success(monkeypatch):
    monkeypatch.setattr(
        llm_client,
        "_http_json",
        lambda url, payload, headers, timeout: {"choices": [{"message": {"content": "轉錄文字"}}]},
    )
    assert llm_client.transcribe_image("data:image/png;base64,AAAA", "key") == "轉錄文字"


@pytest.mark.unit
def test_transcribe_image_network_failure_returns_none(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("down")

    monkeypatch.setattr(llm_client, "_http_json", boom)
    assert llm_client.transcribe_image("data:image/png;base64,AAAA", "key") is None
