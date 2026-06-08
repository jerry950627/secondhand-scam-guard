"""產生與本機 Python 引擎同步的 n8n workflow JSON（單一資料來源）。

知識庫從 content/ 載入、詞表與常數從 src/rules_engine.py 與 text_normalize.py 匯入，
注入到 JS 模板，確保 n8n 永不與 Python 引擎漂移。執行後可刪除此檔。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import rules_engine as R  # noqa: E402
import text_normalize as N  # noqa: E402

KB = list(R.load_knowledge_base())
DATA = {
    "knowledgeBase": KB,
    "SYNONYMS": {k: list(v) for k, v in N.SYNONYMS.items()},
    "SAFE_PHRASES": list(R.SAFE_PAYMENT_PHRASES),
    "SUPPRESS_SIGNALS": list(R.SUPPRESSED_WHEN_SAFE_SIGNALS),
    "SUPPRESS_TERMS": list(R.SUPPRESSED_WHEN_SAFE_TERMS),
    "HIGH_TERMS": list(R.HIGH_TERMS),
    "MEDIUM_TERMS": list(R.MEDIUM_TERMS),
    "PSEUDO_PATTERNS": {k: list(v) for k, v in R.PSEUDO_PATTERNS.items()},
    "SCORING": {
        "SIGNAL_WEIGHT": R.SIGNAL_WEIGHT,
        "MIN_DISPLAY_TOKEN_HITS": R.MIN_DISPLAY_TOKEN_HITS,
        "HIGH_MATCH_THRESHOLD": R.HIGH_MATCH_THRESHOLD,
        "HIGH_BASE_SCORE": R.HIGH_BASE_SCORE,
        "HIGH_SCORE_CAP": R.HIGH_SCORE_CAP,
        "MEDIUM_BASE_SCORE": R.MEDIUM_BASE_SCORE,
        "MEDIUM_SCORE_CAP": R.MEDIUM_SCORE_CAP,
        "LOW_SCORE": R.LOW_SCORE,
        "PER_TERM_POINTS": R.PER_TERM_POINTS,
        "PER_EVIDENCE_POINTS": R.PER_EVIDENCE_POINTS,
    },
}

DATA_JS = "\n".join(f"const {k} = {json.dumps(v, ensure_ascii=False)};" for k, v in DATA.items())

JS_LOGIC = r'''
const body = $json.body || $json;
const inputText = (body.text || body.message || body.caption || body.vlm_text || '買家說無法下單，要求我加 LINE 客服並操作網路銀行做金流驗證').toString();

const SEP_SET = new Set([' ','\t','\n','\r','.','。','．','・','·','‧','-','–','—','_','/','\\','|','~','、','​']);
const SEP_RE = /[\s.。．・·‧\-–—_/\\|~、]+/g;

function nfkc(s){ return s.normalize('NFKC').toLowerCase(); }
function prepare(text){ const normalized = nfkc(text); return { original: text, normalized, compact: normalized.replace(SEP_RE, '') }; }
function variants(term){ return [term].concat(SYNONYMS[term] || []); }

function contains(term, p){
  for(const v of variants(term)){
    const vn = nfkc(v);
    if(p.normalized.includes(vn)) return true;
    const vc = vn.replace(SEP_RE, '');
    if(vc && p.compact.includes(vc)) return true;
  }
  return false;
}
function matchTerms(terms, p){ return terms.filter((t) => contains(t, p)); }

function tokenize(text){
  const lowered = nfkc(text);
  const tokens = new Set();
  (lowered.match(/[a-z0-9]+/g) || []).forEach((w) => tokens.add(w));
  (lowered.match(/[一-鿿]+/g) || []).forEach((run) => {
    if(run.length === 1){ tokens.add(run); return; }
    for(let i = 0; i < run.length - 1; i++) tokens.add(run.slice(i, i + 2));
  });
  return tokens;
}
function intersectCount(a, b){ let n = 0; for(const x of a) if(b.has(x)) n++; return n; }

function findSpans(term, original){
  const spans = [];
  for(const v of variants(term)){
    const t = Array.from(nfkc(v)).filter((c) => c.trim() !== '' && !SEP_SET.has(c));
    if(!t.length) continue;
    for(let start = 0; start < original.length; start++){
      if(nfkc(original[start]) !== t[0]) continue;
      let i = start + 1, ci = 1;
      while(i < original.length && ci < t.length){
        const oc = nfkc(original[i]);
        if(oc === t[ci]){ ci++; i++; }
        else if(SEP_SET.has(original[i])){ i++; }
        else break;
      }
      if(ci === t.length) spans.push([start, i]);
    }
  }
  return spans;
}
function highlightSpans(byLevel, original){
  const rank = { high: 2, medium: 1 };
  const raw = [];
  for(const level of Object.keys(byLevel))
    for(const term of byLevel[level])
      for(const span of findSpans(term, original)) raw.push([span[0], span[1], level]);
  raw.sort((a, b) => (a[0] - b[0]) || ((b[1] - b[0]) - (a[1] - a[0])));
  const merged = [];
  for(const item of raw){
    const start = item[0], end = item[1], level = item[2];
    if(merged.length && start < merged[merged.length - 1].end){
      const last = merged[merged.length - 1];
      last.end = Math.max(last.end, end);
      if(rank[level] > rank[last.level]) last.level = level;
      continue;
    }
    merged.push({ start, end, level });
  }
  return merged;
}

function isSafe(p){ return SAFE_PHRASES.some((ph) => p.normalized.includes(ph.toLowerCase())); }
function pseudoQueries(p){
  const queries = [p.original.trim()];
  const safe = isSafe(p);
  for(const label of Object.keys(PSEUDO_PATTERNS)){
    if(safe && label === '二手交易先匯款風險') continue;
    if(matchTerms(PSEUDO_PATTERNS[label], p).length) queries.push(label);
  }
  return Array.from(new Set(queries));
}
function hydeDocument(text){
  return '這可能是一則二手交易詐騙案例：對方可能以交易異常、金流驗證、物流連結、私下加 LINE、先付訂金或操作 ATM/網銀等理由，誘導使用者離開平台或提供付款資訊。原始描述：' + text;
}
function kbSignalHits(item, p, safe){
  let hits = matchTerms(item.risk_signals, p);
  if(safe) hits = hits.filter((s) => SUPPRESS_SIGNALS.indexOf(s) === -1);
  return hits;
}
function retrieveEvidence(p, queries){
  const safe = isSafe(p);
  const tokens = tokenize(p.normalized + ' ' + queries.join(' '));
  const scored = [];
  for(const item of knowledgeBase){
    const haystack = [item.title, item.guidance, item.risk_signals.join(' ')].join(' ');
    const signalHits = kbSignalHits(item, p, safe);
    const tokenHits = intersectCount(tokens, tokenize(haystack));
    if(!(signalHits.length || tokenHits >= SCORING.MIN_DISPLAY_TOKEN_HITS)) continue;
    scored.push(Object.assign({}, item, { score: tokenHits + signalHits.length * SCORING.SIGNAL_WEIGHT, matched_signals: signalHits }));
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, 3);
}
function safeGuidance(){
  const item = knowledgeBase.find((k) => k.id === 'kb-006');
  return item ? Object.assign({}, item, { score: 0, matched_signals: [] }) : null;
}
function classify(p, evidence){
  const safe = isSafe(p);
  let high = matchTerms(HIGH_TERMS, p);
  let med = matchTerms(MEDIUM_TERMS, p);
  if(safe){
    high = high.filter((t) => SUPPRESS_TERMS.indexOf(t) === -1);
    med = med.filter((t) => SUPPRESS_TERMS.indexOf(t) === -1);
  }
  const mc = evidence.reduce((s, i) => s + i.matched_signals.length, 0);
  if(high.length || mc >= SCORING.HIGH_MATCH_THRESHOLD)
    return { level: '高', score: Math.min(SCORING.HIGH_SCORE_CAP, SCORING.HIGH_BASE_SCORE + high.length * SCORING.PER_TERM_POINTS + mc * SCORING.PER_EVIDENCE_POINTS), high, med };
  if(med.length || (mc >= 1 && !safe))
    return { level: '中', score: Math.min(SCORING.MEDIUM_SCORE_CAP, SCORING.MEDIUM_BASE_SCORE + med.length * SCORING.PER_TERM_POINTS + mc * SCORING.PER_EVIDENCE_POINTS), high: [], med };
  return { level: '低', score: SCORING.LOW_SCORE, high: [], med: [] };
}

const prepared = prepare(inputText);
const queries = pseudoQueries(prepared);
let evidence = retrieveEvidence(prepared, queries);
const result = classify(prepared, evidence);
if(result.level === '低' && !evidence.some((e) => e.matched_signals.length)){
  const g = safeGuidance();
  evidence = g ? [g] : [];
}
const signals = result.level === '高' ? result.high.concat(result.med) : result.level === '中' ? result.med : [];
const evidenceSignals = evidence.reduce((acc, e) => acc.concat(e.matched_signals), []);
const highlights = highlightSpans({ high: result.high.concat(evidenceSignals), medium: result.med }, inputText);

return [{
  json: {
    input_text: inputText,
    risk_level: result.level,
    risk_score: result.score,
    suspicious_signals: signals.length ? signals : ['未偵測到明顯高風險話術'],
    pseudo_queries: queries,
    hyde_document: hydeDocument(inputText),
    highlights: highlights,
    retrieved_evidence: evidence.map((e) => ({ id: e.id, title: e.title, matched_signals: e.matched_signals, source_url: e.source_url })),
    recommended_actions: [
      '不要離開原交易平台進行付款或驗證。',
      '不要點私訊連結，不提供 OTP、網銀帳密或付款 QR Code。',
      '要求賣家提供可驗證的商品照片、平台內交易紀錄與面交/官方付款方式。',
      '若出現客服、金流驗證或帳戶凍結話術，立即停止並撥打 165 查證。'
    ],
    seller_questions: [
      '是否能在原平台完成交易並保留對話紀錄？',
      '是否能提供今天日期手寫紙條與商品同框照片？',
      '是否接受面交或平台內第三方金流？',
      '為什麼需要我加入 LINE 或操作銀行驗證？'
    ],
    implementation_note: '與本機 Python 引擎邏輯同步：知識庫、同義詞、詞表與評分常數皆由 Python 單一來源產生；含 NFKC 正規化、拆字規避 compact 比對、中文 bigram RAG、HyDE 僅展示不計分、低風險只引用安全守則與話術標註。'
  }
}];
'''

JS_CODE = DATA_JS + "\n" + JS_LOGIC.strip() + "\n"

workflow = {
    "name": "FB Threads 二手交易 AI 防踩雷助理",
    "nodes": [
        {
            "parameters": {"httpMethod": "POST", "path": "secondhand-scam-guard", "responseMode": "responseNode", "options": {}},
            "id": "webhook-input",
            "name": "Webhook: 上傳交易文字或截圖分析結果",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-840, 0],
            "webhookId": "secondhand-scam-guard",
        },
        {
            "parameters": {"jsCode": JS_CODE},
            "id": "rag-risk-code",
            "name": "Code: pseudo-query + HyDE + RAG 風險分析（v2 同步）",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-520, 0],
        },
        {
            "parameters": {"respondWith": "json", "responseBody": "={{ $json }}", "options": {}},
            "id": "respond-json",
            "name": "Respond: 回傳風險報告",
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1.1,
            "position": [-200, 0],
        },
    ],
    "connections": {
        "Webhook: 上傳交易文字或截圖分析結果": {"main": [[{"node": "Code: pseudo-query + HyDE + RAG 風險分析（v2 同步）", "type": "main", "index": 0}]]},
        "Code: pseudo-query + HyDE + RAG 風險分析（v2 同步）": {"main": [[{"node": "Respond: 回傳風險報告", "type": "main", "index": 0}]]},
    },
    "pinData": {
        "Webhook: 上傳交易文字或截圖分析結果": [
            {"json": {"body": {"text": "客服請我操作網．路．銀．行做金．流．驗．證，解除帳戶凍結，否則分期設定錯誤會重複扣款"}}}
        ]
    },
    "settings": {"executionOrder": "v1"},
    "staticData": None,
    "tags": [{"name": "final-project"}, {"name": "rag"}, {"name": "anti-fraud"}],
    "triggerCount": 1,
    "updatedAt": "2026-06-06T00:00:00.000Z",
    "versionId": "secondhand-scam-guard-v2",
}

out = ROOT / "n8n" / "secondhand_scam_guard_workflow.json"
out.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("written:", out)
