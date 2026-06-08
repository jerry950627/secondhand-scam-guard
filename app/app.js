const samples = {
  low: "FB 社團貼文：出售二手鍵盤 NT$800，台北捷運站面交，可現場測試，不接受先匯款。私訊可看更多照片。",
  medium: "Threads 上有人賣 iPhone 15 Pro 只要 NT$9000，說很多人問，要先付 NT$1000 訂金才保留，可以寄送但不方便面交。",
  high: "Threads 上看到 AirPods Pro 2 只要 NT$2500，賣家說很多人排隊，要先匯 NT$500 訂金保留，後來傳賣貨便連結叫我加 LINE 客服做金流驗證。"
};

const el = {
  tradeText: document.querySelector("#tradeText"),
  analyzeButton: document.querySelector("#analyzeButton"),
  clearButton: document.querySelector("#clearButton"),
  downloadButton: document.querySelector("#downloadButton"),
  riskLevel: document.querySelector("#riskLevel"),
  scoreCard: document.querySelector("#scoreCard"),
  meter: document.querySelector("#meter"),
  meterFill: document.querySelector("#meterFill"),
  signals: document.querySelector("#signals"),
  evidenceList: document.querySelector("#evidenceList"),
  actions: document.querySelector("#actions"),
  questions: document.querySelector("#questions"),
  pseudoQueries: document.querySelector("#pseudoQueries"),
  hydeText: document.querySelector("#hydeText"),
  timestamp: document.querySelector("#timestamp"),
  serverStatus: document.querySelector("#serverStatus"),
  capturePanel: document.querySelector("#capturePanel"),
  dropZone: document.querySelector("#dropZone"),
  dropEmpty: document.querySelector("#dropEmpty"),
  imageInput: document.querySelector("#imageInput"),
  imagePreview: document.querySelector("#imagePreview"),
  imageStatus: document.querySelector("#imageStatus"),
  clearImageButton: document.querySelector("#clearImageButton"),
  errorBanner: document.querySelector("#errorBanner"),
  synthesis: document.querySelector("#synthesis"),
  modeBadge: document.querySelector("#modeBadge"),
  llmConfidence: document.querySelector("#llmConfidence"),
  synthesisNote: document.querySelector("#synthesisNote"),
  llmReasons: document.querySelector("#llmReasons"),
  comparePanel: document.querySelector("#comparePanel"),
  cmpRules: document.querySelector("#cmpRules"),
  cmpLlm: document.querySelector("#cmpLlm"),
  highlightSection: document.querySelector("#highlightSection"),
  highlightText: document.querySelector("#highlightText"),
  ocrButton: document.querySelector("#ocrButton"),
  cleanTextButton: document.querySelector("#cleanTextButton"),
  printButton: document.querySelector("#printButton"),
  copySummaryButton: document.querySelector("#copySummaryButton"),
  copyQuestionsButton: document.querySelector("#copyQuestionsButton"),
  downloadTextButton: document.querySelector("#downloadTextButton"),
  nextStepCard: document.querySelector("#nextStepCard"),
  nextStepText: document.querySelector("#nextStepText"),
  linkCheckSection: document.querySelector("#linkCheckSection"),
  linkCheckList: document.querySelector("#linkCheckList"),
  quickLinkInput: document.querySelector("#quickLinkInput"),
  quickCheckButton: document.querySelector("#quickCheckButton"),
  quickExampleButton: document.querySelector("#quickExampleButton"),
  quickCheckResult: document.querySelector("#quickCheckResult")
};

let lastResult = null;
let previewUrl = null;
let currentImageFile = null;
let tesseractLoader = null;
let llmAvailable = false;
let analyzeSeq = 0;

// state: "ok"（已連線/完成）｜"busy"（分析中）｜"err"（未連線/失敗），決定狀態列左側色條。
function setServerStatus(text, state = "ok") {
  el.serverStatus.textContent = text;
  el.serverStatus.classList.remove("ok", "busy", "err");
  el.serverStatus.classList.add(state);
}

function setReadyStatus(prefix = "伺服器已連線") {
  setServerStatus(prefix, "ok");
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    llmAvailable = Boolean(data.llm_available);
    setReadyStatus();
  } catch {
    llmAvailable = false;
    setServerStatus("伺服器未連線", "err");
  }
}

const TESSERACT_CDN = "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js";
const OCR_RECOGNITION_OPTIONS = {
  preserve_interword_spaces: "0",
  tessedit_pageseg_mode: "11",
  tessedit_char_blacklist: "®©™●○◎◉□■◆◇★☆"
};
const CJK_RE = /[\u3400-\u9fff]/;
const LETTER_RUN_RE = /\b(?:[a-zA-Z]\s+){2,}[a-zA-Z]\b/g;
const OCR_NOISE_LINE_PATTERNS = [
  /^資料來源[:：]/,
  /market\s*先生/i,
  /^mr\.?\s*market/i,
  /^m\.?r\.?market/i,
  /^(aa|a\.a|a a)$/i,
  /^(me|c me)$/i,
  // 整行只由 FB/IG 介面按鈕文字組成（含 OCR 後去空格的「按讚留言分享」）才視為雜訊。
  /^(?:讚|按讚|留言|分享|傳送|轉發|收藏|儲存|回覆|編輯|檢舉|追蹤|返回|更多|全圖|查看翻譯|顯示更多)+$/i,
  /^(上午|下午)?\s*\d{1,2}:\d{2}$/,
  /^(?:[=\-_.·•●○◎◉□■◆◇★☆~:;|/\\()[\]{}<>，。！？、\s]+)$/
];

function joinSingleLetterRuns(text) {
  return text.replace(LETTER_RUN_RE, (match) => match.replace(/\s+/g, ""));
}

function normalizeOcrLine(line) {
  return joinSingleLetterRuns(line)
    .replace(/[\u200b-\u200d\ufeff]/g, "")
    .replace(/[®©™]/g, "")
    .replace(/([一-鿿])\s+(?=[一-鿿])/g, "$1")
    .replace(/\s+([，。！？、；：])/g, "$1")
    .replace(/([（「『])\s+/g, "$1")
    .replace(/\s+([）」』])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .replace(/^[=_.·•●○◎◉□■◆◇★☆~:;|/\\，。！？、\s-]+/, "")
    .trim();
}

function isLikelyOcrNoiseLine(line) {
  if (!line) return true;
  if (OCR_NOISE_LINE_PATTERNS.some((pattern) => pattern.test(line))) return true;
  const hasCjk = CJK_RE.test(line);
  const hasTime = /(上午|下午)?\s*\d{1,2}:\d{2}/.test(line);
  const hasStatusSignal = /\d{1,3}%|全圖|電量|訊號|wifi|wi-?fi|4g|5g/i.test(line);
  if (hasTime && hasStatusSignal) return true;
  // 短的純英文字母行多半是 ATM/LINE/OTP/VIP 等關鍵字，保留；其餘短雜訊才刪。
  if (!hasCjk && line.length <= 4 && !/^[a-z]{2,4}$/i.test(line)) return true;
  if (!hasCjk) {
    const alnumCount = (line.match(/[a-z0-9]/gi) || []).length;
    return alnumCount / Math.max(line.length, 1) < 0.45;
  }
  const cjkCount = (line.match(/[\u3400-\u9fff]/g) || []).length;
  const symbolCount = (line.match(/[^\u3400-\u9fffA-Za-z0-9]/g) || []).length;
  if (cjkCount <= 1 && line.length <= 10 && /[@#=]|\b[a-z]{1,2}\b/i.test(line)) return true;
  return line.length <= 3 && cjkCount <= 1 && symbolCount >= 1;
}

function cleanOcrText(rawText) {
  const cleaned = [];
  for (const rawLine of rawText.split(/\r?\n/)) {
    const line = normalizeOcrLine(rawLine);
    if (isLikelyOcrNoiseLine(line)) continue;
    cleaned.push(line);
  }
  return cleaned.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function cleanTradeText() {
  const original = el.tradeText.value;
  const cleaned = cleanOcrText(original);
  if (!original.trim()) {
    showError("目前沒有文字可清理。");
    return;
  }
  if (!cleaned) {
    // 全部內容都被判為雜訊：保留原文，但別誤報「沒有雜訊」。
    setImageStatus("清理後內容為空，已保留原文。");
    return;
  }
  if (cleaned === original.trim()) {
    setImageStatus("目前沒有明顯 OCR 雜訊。");
    return;
  }
  el.tradeText.value = cleaned;
  const removed = Math.max(0, original.trim().length - cleaned.length);
  setImageStatus(`已清理 ${removed} 字 OCR 雜訊`);
  clearError();
  el.tradeText.focus();
}

function loadTesseract() {
  if (window.Tesseract) return Promise.resolve(window.Tesseract);
  if (tesseractLoader) return tesseractLoader;
  tesseractLoader = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = TESSERACT_CDN;
    script.onload = () => resolve(window.Tesseract);
    script.onerror = () => reject(new Error("無法載入 OCR 函式庫（首次使用需連網）。"));
    document.head.append(script);
  });
  return tesseractLoader;
}

async function runOcr() {
  if (!currentImageFile) return;
  clearError();
  el.ocrButton.disabled = true;
  const original = el.ocrButton.textContent;
  el.ocrButton.textContent = "辨識中...";
  setImageStatus("OCR 辨識中，首次使用需下載繁中語言包...");
  try {
    const Tesseract = await loadTesseract();
    const { data } = await Tesseract.recognize(currentImageFile, "chi_tra+eng", {
      ...OCR_RECOGNITION_OPTIONS,
      logger: (m) => {
        if (m.status === "recognizing text") {
          setImageStatus(`辨識中 ${(m.progress * 100).toFixed(0)}%`);
        }
      }
    });
    const rawText = (data.text || "").trim();
    if (!rawText) {
      setImageStatus("未辨識到文字，請改用更清晰的截圖。");
      return;
    }
    const cleanedText = cleanOcrText(rawText);
    const text = cleanedText || rawText;
    el.tradeText.value = text;
    const removed = Math.max(0, rawText.length - text.length);
    setImageStatus(`已辨識 ${rawText.length} 字，自動清理 ${removed} 字，已填入下方文字欄`);
    el.tradeText.focus();
  } catch (error) {
    setImageStatus("OCR 失敗");
    showError(error.message || "OCR 失敗，請改用手機/電腦 OCR 後貼上文字。");
  } finally {
    el.ocrButton.textContent = original;
    el.ocrButton.disabled = !currentImageFile;
  }
}

function showError(message) {
  el.errorBanner.textContent = message;
  el.errorBanner.hidden = false;
}

function clearError() {
  el.errorBanner.hidden = true;
  el.errorBanner.textContent = "";
}

function riskClass(level) {
  if (level.includes("高")) return "high";
  if (level.includes("中")) return "medium";
  if (level.includes("低")) return "low";
  return "neutral";
}

function renderList(target, items) {
  target.innerHTML = "";
  for (const item of items || []) {
    const li = document.createElement("li");
    li.textContent = item;
    target.append(li);
  }
}

function renderChips(items) {
  el.signals.innerHTML = "";
  for (const item of items || []) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = item;
    el.signals.append(chip);
  }
}

function renderEvidence(items) {
  el.evidenceList.innerHTML = "";
  if (!items?.length) {
    const empty = document.createElement("p");
    empty.textContent = "尚未找到明確依據。";
    el.evidenceList.append(empty);
    return;
  }

  for (const item of items) {
    const node = document.createElement("article");
    node.className = "evidence-item";
    const title = document.createElement("strong");
    title.textContent = `${item.id}｜${item.title}`;
    const signals = document.createElement("p");
    signals.textContent = `命中訊號：${item.matched_signals?.join("、") || "語意相近"}`;
    const link = document.createElement("a");
    link.href = item.source_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = "查看來源";
    node.append(title, signals, link);
    el.evidenceList.append(node);
  }
}

function nextStepFor(level) {
  if ((level || "").includes("高")) {
    return "先停止交易，不付款、不點連結、不加客服；保留截圖與對話紀錄，必要時撥打 165 查證。";
  }
  if ((level || "").includes("中")) {
    return "先暫停付款，要求留在原平台交易，並用下方查證問題確認賣家與商品真實性。";
  }
  return "目前未見明顯高風險話術，但仍建議保留平台內對話、面交驗貨或使用官方金流。";
}

function formatBulletList(title, items) {
  const values = (items || []).filter(Boolean);
  if (!values.length) return `${title}\n- 無`;
  return `${title}\n${values.map((item) => `- ${item}`).join("\n")}`;
}

function buildSummaryText(result) {
  if (!result) return "";
  const evidence = (result["引用到的防詐依據"] || []).map((item) => {
    const signals = item.matched_signals?.length ? item.matched_signals.join("、") : "語意相近";
    return `- ${item.id}｜${item.title}（${signals}）\n  ${item.source_url}`;
  });
  return [
    "二手交易 AI 防踩雷摘要",
    `風險等級：${result["風險等級"] || "未判定"}風險`,
    `風險分數：${result["風險分數"] ?? "未判定"}`,
    `下一步：${nextStepFor(result["風險等級"])}`,
    "",
    `綜合說明：${result["綜合說明"] || "無"}`,
    "",
    formatBulletList("可疑訊號：", result["可疑訊號"]),
    "",
    formatBulletList("建議行動：", result["建議行動"]),
    "",
    formatBulletList("查證問題：", result["可問賣家的查證問題"]),
    "",
    evidence.length ? `RAG 引用依據：\n${evidence.join("\n")}` : "RAG 引用依據：\n- 無"
  ].join("\n");
}

function buildQuestionsText(result) {
  if (!result) return "";
  return [
    "我想先確認幾件事，避免交易糾紛：",
    ...(result["可問賣家的查證問題"] || []).map((item) => `- ${item}`),
    "",
    "請盡量在原交易平台內回覆與付款，方便保留紀錄，謝謝。"
  ].join("\n");
}

async function copyText(text, button, doneText = "已複製") {
  if (!text) return;
  const original = button.textContent;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    button.textContent = doneText;
  } catch {
    showError("複製失敗，請改用下載文字報告。");
  } finally {
    window.setTimeout(() => {
      button.textContent = original;
    }, 1400);
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderHighlights(result) {
  const text = result["輸入文字"] || "";
  const marks = result["命中話術標註"] || [];
  if (!text || !marks.length) {
    el.highlightSection.hidden = true;
    el.highlightText.innerHTML = "";
    return;
  }
  // 標註位移來自 Python（以「碼位 / code point」計）；JS 字串 slice 以 UTF-16
  // code unit 計，遇 emoji 等星平面字元會錯位。改用碼位陣列切片以對齊 Python。
  const cp = Array.from(text);
  const sorted = [...marks].sort((a, b) => a.start - b.start);
  let cursor = 0;
  let html = "";
  for (const mark of sorted) {
    if (mark.start < cursor) continue;
    html += escapeHtml(cp.slice(cursor, mark.start).join(""));
    const fragment = escapeHtml(cp.slice(mark.start, mark.end).join(""));
    html += `<mark class="hl-${mark.level}">${fragment}</mark>`;
    cursor = mark.end;
  }
  html += escapeHtml(cp.slice(cursor).join(""));
  el.highlightText.innerHTML = html;
  el.highlightSection.hidden = false;
}

function renderSynthesis(result, llmPending) {
  const note = result["綜合說明"];
  const llm = result["LLM研判"];
  const rules = result["規則研判"] || {};
  el.synthesis.hidden = false;
  el.cmpRules.textContent = rules["風險等級"]
    ? `${rules["風險等級"]}風險 · ${rules["風險分數"]}`
    : "—";

  if (result.llm_used && llm) {
    el.modeBadge.textContent = `4B LLM 模式 · ${llm["模型"] || "LLM"}`;
    el.modeBadge.className = "mode-badge llm";
    el.llmConfidence.textContent = "綜合取較高風險";
    el.cmpLlm.textContent = `${llm["風險等級"]}風險 · 信心 ${llm["信心"]}`;
    el.synthesisNote.textContent = note || "";
    renderList(el.llmReasons, llm["理由"]);
  } else if (llmPending) {
    el.modeBadge.textContent = "規則即時結果 · 4B LLM 研判中…";
    el.modeBadge.className = "mode-badge pending";
    el.llmConfidence.textContent = "";
    el.cmpLlm.textContent = "研判中…";
    el.synthesisNote.textContent = "已用規則引擎即時研判，4B LLM 語意研判中…";
    el.llmReasons.innerHTML = "";
  } else {
    el.modeBadge.textContent = "離線規則模式";
    el.modeBadge.className = "mode-badge rules";
    el.llmConfidence.textContent = "";
    el.cmpLlm.textContent = "未啟用";
    el.synthesisNote.textContent = note || "";
    el.llmReasons.innerHTML = "";
  }
}

function riskBadgeClass(level) {
  if (level === "高") return "lc-high";
  if (level === "中") return "lc-medium";
  return "lc-low";
}

function linkCheckItemNode(item) {
  const node = document.createElement("article");
  node.className = "link-check-item";

  const head = document.createElement("div");
  head.className = "link-check-head";
  const badge = document.createElement("span");
  badge.className = `lc-badge ${riskBadgeClass(item["風險"])}`;
  badge.textContent = `${item["風險"]}風險`;
  const value = document.createElement("code");
  value.className = "lc-value";
  value.textContent = `${item["類型"] === "phone" ? "☎" : "🔗"} ${item["內容"]}`;
  head.append(badge, value);

  const reason = document.createElement("p");
  reason.className = "lc-reason";
  reason.textContent = item["原因"];

  const links = document.createElement("div");
  links.className = "lc-links";
  for (const link of item["查證連結"] || []) {
    const a = document.createElement("a");
    a.href = link.href;
    a.target = "_blank";
    a.rel = "noreferrer";
    a.textContent = link.label;
    links.append(a);
  }

  node.append(head, reason, links);
  return node;
}

function renderLinkCheck(result) {
  const data = result["連結與電話查核"];
  const items = data?.["項目"] || [];
  el.linkCheckList.innerHTML = "";
  if (!items.length) {
    el.linkCheckSection.hidden = true;
    return;
  }
  for (const item of items) {
    el.linkCheckList.append(linkCheckItemNode(item));
  }
  el.linkCheckSection.hidden = false;
}

function renderQuickResult(data) {
  el.quickCheckResult.innerHTML = "";
  el.quickCheckResult.hidden = false;
  const items = data["項目"] || [];
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "qc-empty";
    empty.textContent = "未偵測到可查的網址或電話。請貼上完整連結（含 http）或電話號碼。";
    el.quickCheckResult.append(empty);
    return;
  }
  const overall = document.createElement("div");
  overall.className = `qc-overall ${riskBadgeClass(data["整體連結電話風險"])}`;
  overall.textContent = `整體研判：${data["整體連結電話風險"]}風險`;
  el.quickCheckResult.append(overall);
  for (const item of items) {
    el.quickCheckResult.append(linkCheckItemNode(item));
  }
}

async function quickCheck() {
  const text = el.quickLinkInput.value.trim();
  if (!text) {
    el.quickLinkInput.focus();
    return;
  }
  el.quickCheckButton.disabled = true;
  const original = el.quickCheckButton.textContent;
  el.quickCheckButton.textContent = "查詢中...";
  try {
    const response = await fetch("/api/check-link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "查詢失敗");
    renderQuickResult(data);
  } catch (error) {
    el.quickCheckResult.hidden = false;
    el.quickCheckResult.innerHTML = "";
    const fail = document.createElement("p");
    fail.className = "qc-empty";
    fail.textContent = error.message || "查詢失敗，請稍後再試。";
    el.quickCheckResult.append(fail);
  } finally {
    el.quickCheckButton.disabled = false;
    el.quickCheckButton.textContent = original;
  }
}

function renderResult(result, options = {}) {
  lastResult = result;
  const level = result["風險等級"];
  const score = Number(result["風險分數"] || 0);
  const type = riskClass(level || "");
  el.scoreCard.className = `score-card ${type}`;
  el.riskLevel.textContent = level ? `${level}風險 · ${score}` : "等待輸入";
  const clampedScore = Math.max(0, Math.min(100, score));
  el.meterFill.style.width = `${clampedScore}%`;
  el.meter.setAttribute("aria-valuenow", String(Math.round(clampedScore)));
  el.meterFill.style.background = type === "high" ? "var(--coral)" : type === "medium" ? "var(--amber)" : "var(--green)";
  el.timestamp.textContent = new Date().toLocaleString("zh-TW");

  renderSynthesis(result, Boolean(options.llmPending));
  renderHighlights(result);
  renderLinkCheck(result);
  renderChips(result["可疑訊號"]);
  renderEvidence(result["引用到的防詐依據"]);
  renderList(el.actions, result["建議行動"]);
  renderList(el.questions, result["可問賣家的查證問題"]);
  renderList(el.pseudoQueries, result.pseudo_queries);
  el.hydeText.textContent = result["HyDE假想文件"] || "尚未產生。";
  el.nextStepText.textContent = nextStepFor(level);
  el.nextStepCard.hidden = false;
  el.downloadButton.disabled = false;
  el.printButton.disabled = false;
  el.copySummaryButton.disabled = false;
  el.copyQuestionsButton.disabled = false;
  el.downloadTextButton.disabled = false;
}

function setImageStatus(message) {
  el.imageStatus.textContent = message;
}

function clearImage() {
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  }
  el.imagePreview.hidden = true;
  el.imagePreview.removeAttribute("src");
  el.dropEmpty.hidden = false;
  el.clearImageButton.disabled = true;
  el.ocrButton.disabled = true;
  el.imageInput.value = "";
  currentImageFile = null;
  setImageStatus("尚未載入圖片");
  setReadyStatus();
}

function loadImageFile(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    setImageStatus("請選擇圖片檔");
    return;
  }

  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(file);
  currentImageFile = file;
  el.imagePreview.src = previewUrl;
  el.imagePreview.hidden = false;
  el.dropEmpty.hidden = true;
  el.clearImageButton.disabled = false;
  el.ocrButton.disabled = false;
  setImageStatus(`${file.name || "截圖"} · ${(file.size / 1024).toFixed(0)} KB`);
  setReadyStatus("截圖已載入");
}

function imageFromPaste(event) {
  const items = Array.from(event.clipboardData?.items || []);
  const imageItem = items.find((item) => item.type.startsWith("image/"));
  if (!imageItem) return;
  const file = imageItem.getAsFile();
  if (!file) return;
  event.preventDefault();
  loadImageFile(file);
}

async function postAnalyze(text, withLlm) {
  const url = withLlm ? "/api/analyze" : "/api/analyze?llm=0";
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text })
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "分析失敗");
  return data;
}

async function analyze() {
  const text = el.tradeText.value.trim();
  if (!text) {
    showError("請先輸入交易文字再分析。");
    el.tradeText.focus();
    return;
  }

  clearError();
  const seq = ++analyzeSeq;
  const stale = () => seq !== analyzeSeq;
  el.analyzeButton.disabled = true;
  el.analyzeButton.textContent = "分析中...";
  setServerStatus("分析中", "busy");

  try {
    if (llmAvailable) {
      // 先用規則引擎即時回應，讓報告立刻更新；4B LLM 研判完再覆蓋。
      const fast = await postAnalyze(text, false);
      if (stale()) return;
      renderResult(fast, { llmPending: true });
      setServerStatus("即時結果已更新 · 語意研判中", "busy");

      const full = await postAnalyze(text, true);
      if (stale()) return;
      renderResult(full, { llmPending: false });
      setServerStatus("分析完成", "ok");
    } else {
      const data = await postAnalyze(text, true);
      if (stale()) return;
      renderResult(data, { llmPending: false });
      setServerStatus("分析完成", "ok");
    }
  } catch (error) {
    if (stale()) return;
    setServerStatus("連線失敗", "err");
    showError(error.message || "分析失敗，請稍後再試。");
  } finally {
    if (!stale()) {
      el.analyzeButton.disabled = false;
      el.analyzeButton.textContent = "分析風險";
    }
  }
}

function downloadResult() {
  if (!lastResult) return;
  const blob = new Blob([JSON.stringify(lastResult, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "secondhand-scam-report.json";
  link.click();
  URL.revokeObjectURL(url);
}

function downloadTextReport() {
  if (!lastResult) return;
  const blob = new Blob([buildSummaryText(lastResult)], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "secondhand-scam-report.txt";
  link.click();
  URL.revokeObjectURL(url);
}

document.querySelectorAll("[data-sample]").forEach((button) => {
  button.addEventListener("click", () => {
    el.tradeText.value = samples[button.dataset.sample];
    analyze();
  });
});

el.imageInput.addEventListener("change", (event) => {
  loadImageFile(event.target.files?.[0]);
});

el.clearImageButton.addEventListener("click", clearImage);
el.ocrButton.addEventListener("click", runOcr);
el.cleanTextButton.addEventListener("click", cleanTradeText);
el.printButton.addEventListener("click", () => {
  if (lastResult) window.print();
});

el.quickCheckButton.addEventListener("click", quickCheck);
el.quickExampleButton.addEventListener("click", () => {
  el.quickLinkInput.value = "http://shopee-tw.xyz/pay";
  quickCheck();
});
el.quickLinkInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    quickCheck();
  }
});

el.dropZone.addEventListener("keydown", (event) => {
  // drop-zone 有 role="button"/tabindex=0，補上鍵盤啟動（Enter/Space 開檔案選擇）。
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    el.imageInput.click();
  }
});

el.dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  el.dropZone.classList.add("dragging");
});

el.dropZone.addEventListener("dragleave", () => {
  el.dropZone.classList.remove("dragging");
});

el.dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  el.dropZone.classList.remove("dragging");
  loadImageFile(event.dataTransfer?.files?.[0]);
});

document.addEventListener("paste", imageFromPaste);

el.analyzeButton.addEventListener("click", analyze);
el.downloadButton.addEventListener("click", downloadResult);
el.downloadTextButton.addEventListener("click", downloadTextReport);
el.copySummaryButton.addEventListener("click", () => {
  copyText(buildSummaryText(lastResult), el.copySummaryButton, "摘要已複製");
});
el.copyQuestionsButton.addEventListener("click", () => {
  copyText(buildQuestionsText(lastResult), el.copyQuestionsButton, "問題已複製");
});
el.clearButton.addEventListener("click", () => {
  el.tradeText.value = "";
  clearError();
  el.tradeText.focus();
});

el.tradeText.value = samples.high;
checkHealth();
