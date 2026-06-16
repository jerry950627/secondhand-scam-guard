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
  dropHint: document.querySelector("#dropHint"),
  imageInput: document.querySelector("#imageInput"),
  imageThumbs: document.querySelector("#imageThumbs"),
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
  cmpLlmLabel: document.querySelector("#cmpLlmLabel"),
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
  attackChainSection: document.querySelector("#attackChainSection"),
  attackChain: document.querySelector("#attackChain"),
  attackNext: document.querySelector("#attackNext"),
  safeReplySection: document.querySelector("#safeReplySection"),
  safeReplies: document.querySelector("#safeReplies"),
  linkCheckSection: document.querySelector("#linkCheckSection"),
  linkCheckList: document.querySelector("#linkCheckList"),
  quickLinkInput: document.querySelector("#quickLinkInput"),
  quickCheckButton: document.querySelector("#quickCheckButton"),
  quickExampleButton: document.querySelector("#quickExampleButton"),
  quickCheckResult: document.querySelector("#quickCheckResult"),
  modeModal: document.querySelector("#modeModal"),
  modeKeyRow: document.querySelector("#modeKeyRow"),
  geminiKeyInput: document.querySelector("#geminiKeyInput"),
  modeConfirm: document.querySelector("#modeConfirm"),
  modeSwitchButton: document.querySelector("#modeSwitchButton"),
  llmSetup: document.querySelector("#llmSetup"),
  llmSetupStatus: document.querySelector("#llmSetupStatus"),
  llmProgress: document.querySelector("#llmProgress"),
  llmProgressFill: document.querySelector("#llmProgressFill"),
  llmProgressText: document.querySelector("#llmProgressText"),
  llmDownloadBtn: document.querySelector("#llmDownloadBtn"),
  llmRecheckBtn: document.querySelector("#llmRecheckBtn"),
  llmSkipBtn: document.querySelector("#llmSkipBtn"),
  qrButton: document.querySelector("#qrButton"),
  kbGuideButton: document.querySelector("#kbGuideButton"),
  kbGuideFooter: document.querySelector("#kbGuideFooter"),
  kbModal: document.querySelector("#kbModal"),
  kbModalClose: document.querySelector("#kbModalClose"),
  kbGrid: document.querySelector("#kbGrid")
};

let lastResult = null;
let images = [];   // 多張截圖：{ file, url }，依序辨識合併
const MAX_IMAGES = 8;
let tesseractLoader = null;
let llmAvailable = false;
let analyzeSeq = 0;
let currentMode = null;   // "offline" | "online"，由啟動 modal 決定
let geminiKey = "";       // 線上版金鑰：僅存記憶體、不寫 localStorage、重整即清
let pendingMode = null;   // modal 內暫存的選擇
let llmReady = false;     // 本機 LLM（gemma3:4b）是否就緒
let llmSkipRules = false; // 離線版逃生口：改用純規則（不需 LLM）
let llmPollTimer = null;  // 下載進度輪詢計時器

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
    // 已選好模式就由 applyModeStatus 顯示，避免覆蓋掉「離線/雲端模式」字樣。
    if (!currentMode) setReadyStatus();
    else applyModeStatus();
  } catch {
    llmAvailable = false;
    setServerStatus("伺服器未連線", "err");
  }
}

// ---- 離線/線上模式：啟動 modal 與狀態 ----

function applyModeStatus() {
  if (currentMode === "online") {
    setServerStatus("雲端模式（Gemini）", "ok");
    el.ocrButton.textContent = "用 Gemini 看圖（VLM）";
    el.dropHint.textContent = "按「用 Gemini 看圖（VLM）」雲端辨識，多張會一起判讀。";
  } else {
    setServerStatus("離線模式（本機）", "ok");
    el.ocrButton.textContent = "辨識文字 OCR";
    el.dropHint.textContent = "按「辨識文字 OCR」本機離線辨識，首次使用需連網下載語言包。";
  }
}

function shouldUseLlm() {
  return currentMode === "online" ? Boolean(geminiKey) : llmAvailable;
}

function refreshModeConfirm() {
  const offlineOk = pendingMode === "offline" && (llmReady || llmSkipRules);
  const onlineOk = pendingMode === "online" && el.geminiKeyInput.value.trim().length > 0;
  el.modeConfirm.disabled = !(offlineOk || onlineOk);
}

// ---- 離線版：本機 LLM 狀態 / 下載 ----

function stopLlmPoll() {
  if (llmPollTimer) {
    clearInterval(llmPollTimer);
    llmPollTimer = null;
  }
}

async function checkLlmStatus() {
  stopLlmPoll();
  el.llmProgress.hidden = true;
  el.llmDownloadBtn.hidden = true;
  el.llmRecheckBtn.hidden = true;
  el.llmSetupStatus.textContent = "檢查本機 LLM 狀態中…";
  el.llmSetupStatus.className = "llm-setup-status";
  let status;
  try {
    status = await (await fetch("/api/llm-status")).json();
  } catch {
    status = { ollama: false, ready: false };
  }
  if (status.ready) {
    llmReady = true;
    llmAvailable = true;
    el.llmSetupStatus.textContent = `✓ 本機 LLM 已就緒（${status.model || "gemma3:4b"}），分析會加上小模型研判。`;
    el.llmSetupStatus.className = "llm-setup-status ok";
    el.llmSkipBtn.hidden = true;
  } else if (status.ollama) {
    llmReady = false;
    el.llmSetupStatus.textContent = "尚未下載本機 LLM 模型，下載後離線也能用小模型研判。";
    el.llmDownloadBtn.hidden = false;
    el.llmSkipBtn.hidden = false;
  } else {
    llmReady = false;
    el.llmSetupStatus.textContent = "本機 LLM 服務未啟動。請執行 Start-UI.ps1（會自動啟動 Ollama）後按重新檢查。";
    el.llmRecheckBtn.hidden = false;
    el.llmSkipBtn.hidden = false;
  }
  refreshModeConfirm();
}

function pollPullProgress() {
  stopLlmPoll();
  llmPollTimer = setInterval(async () => {
    let p;
    try {
      p = await (await fetch("/api/llm-pull-progress")).json();
    } catch {
      return;
    }
    el.llmProgressFill.style.width = `${p.percent || 0}%`;
    el.llmProgressText.textContent = p.error ? "下載失敗" : `${p.percent || 0}%　${p.status || ""}`;
    if (p.done) {
      stopLlmPoll();
      if (p.error) {
        el.llmSetupStatus.textContent = `下載失敗：${p.error}`;
        el.llmDownloadBtn.hidden = false;
      } else {
        checkLlmStatus();   // 下載完成 → 重新檢查 → 就緒
      }
    }
  }, 1500);
}

async function startLlmDownload() {
  el.llmDownloadBtn.hidden = true;
  el.llmProgress.hidden = false;
  el.llmProgressFill.style.width = "0%";
  el.llmProgressText.textContent = "準備下載…";
  el.llmSetupStatus.textContent = "正在下載本機 LLM（約 3.3GB，依網速數分鐘）…";
  try {
    const resp = await fetch("/api/llm-pull", { method: "POST" });
    if (!resp.ok) {
      const data = await resp.json();
      throw new Error(data.error || "下載啟動失敗");
    }
  } catch (error) {
    el.llmProgress.hidden = true;
    el.llmDownloadBtn.hidden = false;
    el.llmSetupStatus.textContent = error.message || "下載啟動失敗，請確認 Ollama 已啟動。";
    return;
  }
  pollPullProgress();
}

function skipLlmToRules() {
  llmSkipRules = true;
  llmAvailable = false;
  stopLlmPoll();
  el.llmProgress.hidden = true;
  el.llmDownloadBtn.hidden = true;
  el.llmSetupStatus.textContent = "已選擇純規則模式：規則引擎＋知識庫＋RAG，不使用小模型。";
  el.llmSetupStatus.className = "llm-setup-status";
  refreshModeConfirm();
}

function selectPendingMode(mode) {
  pendingMode = mode;
  for (const btn of el.modeModal.querySelectorAll(".mode-choice")) {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  }
  el.modeKeyRow.hidden = mode !== "online";
  el.llmSetup.hidden = mode !== "offline";
  if (mode === "online") {
    el.geminiKeyInput.focus();
  } else {
    llmSkipRules = false;
    checkLlmStatus();   // 即時偵測本機 LLM（修好「啟動時偵測一次就過時」的問題）
  }
  refreshModeConfirm();
}

function openModeModal() {
  pendingMode = currentMode;
  llmSkipRules = false;
  el.geminiKeyInput.value = geminiKey;   // 同一 session 重開時回填，仍只在記憶體
  if (currentMode) selectPendingMode(currentMode);
  else {
    pendingMode = null;
    for (const btn of el.modeModal.querySelectorAll(".mode-choice")) btn.classList.remove("active");
    el.modeKeyRow.hidden = true;
    el.llmSetup.hidden = true;
    el.modeConfirm.disabled = true;
  }
  el.modeModal.hidden = false;
}

function closeModeModal() {
  stopLlmPoll();
  el.modeModal.hidden = true;
}

function confirmMode() {
  if (!pendingMode) return;
  currentMode = pendingMode;
  geminiKey = currentMode === "online" ? el.geminiKeyInput.value.trim() : "";
  if (currentMode === "offline") llmAvailable = llmReady && !llmSkipRules;
  closeModeModal();
  applyModeStatus();
}

function initModeModal() {
  for (const btn of el.modeModal.querySelectorAll(".mode-choice")) {
    btn.addEventListener("click", () => selectPendingMode(btn.dataset.mode));
  }
  el.geminiKeyInput.addEventListener("input", refreshModeConfirm);
  el.geminiKeyInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !el.modeConfirm.disabled) confirmMode();
  });
  el.llmDownloadBtn.addEventListener("click", startLlmDownload);
  el.llmRecheckBtn.addEventListener("click", checkLlmStatus);
  el.llmSkipBtn.addEventListener("click", skipLlmToRules);
  el.modeConfirm.addEventListener("click", confirmMode);
  el.modeSwitchButton.addEventListener("click", openModeModal);
  // 已選過模式才允許點背景關閉（避免首次未選就略過）。
  el.modeModal.addEventListener("click", (event) => {
    if (event.target === el.modeModal && currentMode) closeModeModal();
  });
}

const TESSERACT_CDN = "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js";
const JSQR_CDN = "https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js";
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
  if (!images.length) return;
  clearError();
  el.ocrButton.disabled = true;
  const original = el.ocrButton.textContent;
  el.ocrButton.textContent = "辨識中...";
  setImageStatus("OCR 辨識中，首次使用需下載繁中語言包...");
  try {
    const Tesseract = await loadTesseract();
    const parts = [];
    for (let i = 0; i < images.length; i++) {
      const { data } = await Tesseract.recognize(images[i].file, "chi_tra+eng", {
        ...OCR_RECOGNITION_OPTIONS,
        logger: (m) => {
          if (m.status === "recognizing text") {
            setImageStatus(`辨識中 ${i + 1}/${images.length} · ${(m.progress * 100).toFixed(0)}%`);
          }
        }
      });
      const raw = (data.text || "").trim();
      if (raw) parts.push(cleanOcrText(raw) || raw);
    }
    const text = parts.join("\n");
    if (!text) {
      setImageStatus("未辨識到文字，請改用更清晰的截圖。");
      return;
    }
    el.tradeText.value = text;
    setImageStatus(`已辨識 ${images.length} 張、共 ${text.length} 字，已填入下方文字欄`);
    el.tradeText.focus();
  } catch (error) {
    setImageStatus("OCR 失敗");
    showError(error.message || "OCR 失敗，請改用手機/電腦 OCR 後貼上文字。");
  } finally {
    el.ocrButton.textContent = original;
    el.ocrButton.disabled = images.length === 0;
  }
}

// 上傳前在前端縮圖壓縮，降低 payload 與 Gemini 成本（最長邊 maxEdge、JPEG quality）。
function downscaleImage(file, maxEdge = 1280, quality = 0.8) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, maxEdge / Math.max(img.width, img.height));
      const w = Math.max(1, Math.round(img.width * scale));
      const h = Math.max(1, Math.round(img.height * scale));
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      canvas.getContext("2d").drawImage(img, 0, 0, w, h);
      resolve(canvas.toDataURL("image/jpeg", quality));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("無法讀取圖片"));
    };
    img.src = url;
  });
}

// 線上版：多張截圖一起交給後端代呼叫 Gemini 多模態（VLM）逐字轉錄。
async function runVlm() {
  if (!images.length) return;
  if (!geminiKey) {
    showError("線上版看圖需先輸入 Gemini API key。");
    openModeModal();
    return;
  }
  clearError();
  el.ocrButton.disabled = true;
  const original = el.ocrButton.textContent;
  el.ocrButton.textContent = "看圖中...";
  setImageStatus(`Gemini 看圖辨識中（${images.length} 張）...`);
  try {
    const dataUrls = [];
    for (const item of images) dataUrls.push(await downscaleImage(item.file));
    const response = await fetch("/api/vlm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ images: dataUrls, geminiKey })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "看圖失敗");
    const text = (data.text || "").trim();
    if (!text) {
      setImageStatus("Gemini 未讀到文字，請改用更清晰的截圖。");
      return;
    }
    el.tradeText.value = text;
    setImageStatus(`Gemini 已讀出 ${images.length} 張、共 ${text.length} 字，已填入下方文字欄`);
    el.tradeText.focus();
  } catch (error) {
    setImageStatus("看圖失敗");
    showError(error.message || "Gemini 看圖失敗，請確認金鑰或改用離線 OCR。");
  } finally {
    el.ocrButton.textContent = original;
    el.ocrButton.disabled = images.length === 0;
  }
}

// 依模式分流：離線→tesseract OCR；線上→Gemini VLM。
function recognizeImage() {
  return currentMode === "online" ? runVlm() : runOcr();
}

// ---- QR Code 解析（前端 jsQR）→ 接既有連結/電話查核 ----

let jsqrLoader = null;
function loadJsQR() {
  if (window.jsQR) return Promise.resolve(window.jsQR);
  if (jsqrLoader) return jsqrLoader;
  jsqrLoader = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = JSQR_CDN;
    script.onload = () => resolve(window.jsQR);
    script.onerror = () => reject(new Error("無法載入 QR 函式庫（需連網）。"));
    document.head.append(script);
  });
  return jsqrLoader;
}

function decodeQrFromFile(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const w = img.naturalWidth;
      const h = img.naturalHeight;
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0, w, h);
      const data = ctx.getImageData(0, 0, w, h);
      const code = window.jsQR(data.data, w, h);
      resolve(code ? code.data : null);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("無法讀取圖片"));
    };
    img.src = url;
  });
}

async function runQrScan() {
  if (!images.length) return;
  clearError();
  el.qrButton.disabled = true;
  const original = el.qrButton.textContent;
  el.qrButton.textContent = "解析中...";
  setImageStatus("解析 QR Code 中...");
  try {
    await loadJsQR();
    const found = [];
    for (const item of images) {
      const decoded = await decodeQrFromFile(item.file);
      if (decoded && !found.includes(decoded)) found.push(decoded);
    }
    if (!found.length) {
      setImageStatus("未在截圖中找到 QR Code（請確認 QR 清晰、未被裁切）。");
      return;
    }
    // 把解出的內容丟給既有的連結/電話查核（黑名單 + 啟發式）。
    const joined = found.join("\n");
    el.quickLinkInput.value = found.length === 1 ? found[0] : joined;
    setImageStatus(`解出 ${found.length} 個 QR 內容，已送查核`);
    const response = await fetch("/api/check-link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: joined })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "查核失敗");
    renderQuickResult(data);
    el.quickCheckResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    setImageStatus("QR 解析失敗");
    showError(error.message || "QR 解析失敗，請改用清晰截圖或手動貼上連結。");
  } finally {
    el.qrButton.textContent = original;
    el.qrButton.disabled = images.length === 0;
  }
}

// ---- 詐騙樣態圖鑑 modal ----

let kbCache = null;
async function loadKnowledgeBase() {
  if (kbCache) return kbCache;
  const response = await fetch("/api/knowledge-base");
  if (!response.ok) throw new Error("無法載入知識庫");
  kbCache = await response.json();
  return kbCache;
}

function renderKbCards(items) {
  el.kbGrid.innerHTML = "";
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "kb-card";

    const head = document.createElement("div");
    head.className = "kb-card-head";
    const title = document.createElement("h3");
    title.textContent = item.title || item.id;
    head.append(title);
    if ((item.source || "").includes("政府開放資料")) {
      const badge = document.createElement("span");
      badge.className = "kb-badge";
      badge.textContent = "政府開放資料";
      head.append(badge);
    }
    card.append(head);

    const chips = document.createElement("div");
    chips.className = "kb-chips";
    for (const sig of (item.risk_signals || []).slice(0, 8)) {
      const chip = document.createElement("span");
      chip.className = "kb-chip";
      chip.textContent = sig;
      chips.append(chip);
    }
    if (chips.childElementCount) card.append(chips);

    if (item.guidance) {
      const guidance = document.createElement("p");
      guidance.className = "kb-guidance";
      guidance.textContent = item.guidance;
      card.append(guidance);
    }

    if (item.source_url) {
      const source = document.createElement("a");
      source.className = "kb-source";
      source.href = item.source_url;
      source.target = "_blank";
      source.rel = "noreferrer";
      source.textContent = `來源：${item.source || "查看"} ↗`;
      card.append(source);
    }
    el.kbGrid.append(card);
  }
}

async function openKbModal() {
  el.kbModal.hidden = false;
  if (kbCache) return;
  el.kbGrid.innerHTML = '<p class="kb-loading">載入中…</p>';
  try {
    renderKbCards(await loadKnowledgeBase());
  } catch {
    el.kbGrid.innerHTML = '<p class="kb-loading">載入失敗，請重整再試。</p>';
  }
}

function closeKbModal() {
  el.kbModal.hidden = true;
}

function initKbModal() {
  el.kbGuideButton.addEventListener("click", openKbModal);
  if (el.kbGuideFooter) el.kbGuideFooter.addEventListener("click", openKbModal);
  el.kbModalClose.addEventListener("click", closeKbModal);
  el.kbModal.addEventListener("click", (event) => {
    if (event.target === el.kbModal) closeKbModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !el.kbModal.hidden) closeKbModal();
  });
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

  const isOnline = result["分析模式"] === "online" || currentMode === "online";
  const pendLabel = isOnline ? "Gemini 研判中…" : "4B LLM 研判中…";
  el.cmpLlmLabel.textContent = isOnline ? "雲端 Gemini" : "本機 4B LLM";

  if (result.llm_used && llm) {
    el.modeBadge.textContent = isOnline
      ? `雲端 Gemini · ${llm["模型"] || "gemini"}`
      : `本機 4B LLM · ${llm["模型"] || "LLM"}`;
    el.modeBadge.className = "mode-badge llm";
    el.llmConfidence.textContent = "綜合取較高風險";
    el.cmpLlm.textContent = `${llm["風險等級"]}風險 · 信心 ${llm["信心"]}`;
    el.synthesisNote.textContent = note || "";
    renderList(el.llmReasons, llm["理由"]);
  } else if (llmPending) {
    el.modeBadge.textContent = `規則即時結果 · ${pendLabel}`;
    el.modeBadge.className = "mode-badge pending";
    el.llmConfidence.textContent = "";
    el.cmpLlm.textContent = "研判中…";
    el.synthesisNote.textContent = `已用規則引擎即時研判，${pendLabel}`;
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
  renderAttackChain(result);
  renderHighlights(result);
  renderLinkCheck(result);
  renderChips(result["可疑訊號"]);
  renderEvidence(result["引用到的防詐依據"]);
  renderList(el.actions, result["建議行動"]);
  renderList(el.questions, result["可問賣家的查證問題"]);
  renderSafeReplies(result["安全回覆建議"]);
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

function renderAttackChain(result) {
  const chain = result["攻擊鏈"];
  if (!chain || !Array.isArray(chain.stages)) {
    el.attackChainSection.hidden = true;
    return;
  }
  el.attackChain.innerHTML = "";
  const current = Number(chain.current_stage || 0);
  for (const stage of chain.stages) {
    const node = document.createElement("div");
    let cls = "chain-stage";
    if (stage.id === current) cls += " current";
    else if (stage.detected && stage.id < current) cls += " passed";
    node.className = cls;

    const dot = document.createElement("span");
    dot.className = "chain-dot";
    dot.textContent = stage.id;
    const name = document.createElement("span");
    name.className = "chain-name";
    name.textContent = stage.name;
    node.append(dot, name);

    if (stage.hits && stage.hits.length) {
      const hits = document.createElement("span");
      hits.className = "chain-hits";
      hits.textContent = stage.hits.slice(0, 3).join("、");
      node.append(hits);
    }
    el.attackChain.append(node);
  }
  el.attackNext.textContent = `預測下一步：${chain.next_prediction || ""}`;
  el.attackChainSection.hidden = false;
}

function renderSafeReplies(replies) {
  const list = Array.isArray(replies) ? replies : [];
  el.safeReplies.innerHTML = "";
  if (!list.length) {
    el.safeReplySection.hidden = true;
    return;
  }
  for (const text of list) {
    const row = document.createElement("div");
    row.className = "safe-reply";
    const para = document.createElement("p");
    para.className = "safe-reply-text";
    para.textContent = text;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button compact-button safe-reply-copy";
    button.textContent = "複製";
    button.addEventListener("click", () => copyText(text, button, "已複製"));
    row.append(para, button);
    el.safeReplies.append(row);
  }
  el.safeReplySection.hidden = false;
}

function setImageStatus(message) {
  el.imageStatus.textContent = message;
}

// 重畫縮圖牆，並依是否有圖切換空狀態與按鈕可用性。
function renderThumbs() {
  el.imageThumbs.innerHTML = "";
  images.forEach((item, i) => {
    const thumb = document.createElement("div");
    thumb.className = "image-thumb";

    const img = document.createElement("img");
    img.src = item.url;
    img.alt = `截圖 ${i + 1}`;

    const idx = document.createElement("span");
    idx.className = "image-thumb-index";
    idx.textContent = i + 1;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "image-thumb-remove";
    remove.title = "移除這張";
    remove.setAttribute("aria-label", `移除截圖 ${i + 1}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => removeImageAt(i));

    thumb.append(img, idx, remove);
    el.imageThumbs.append(thumb);
  });
  const has = images.length > 0;
  el.imageThumbs.hidden = !has;
  el.dropEmpty.hidden = has;
  el.clearImageButton.disabled = !has;
  el.ocrButton.disabled = !has;
  el.qrButton.disabled = !has;
}

function addImages(fileList) {
  const incoming = Array.from(fileList || []).filter((f) => f && f.type.startsWith("image/"));
  if (!incoming.length) {
    if (fileList && fileList.length) setImageStatus("請選擇圖片檔");
    return;
  }
  let added = 0;
  for (const file of incoming) {
    if (images.length >= MAX_IMAGES) break;
    images.push({ file, url: URL.createObjectURL(file) });
    added++;
  }
  renderThumbs();
  el.imageInput.value = "";
  const skipped = incoming.length - added;
  const note = skipped > 0 ? `（已達上限 ${MAX_IMAGES} 張，略過 ${skipped} 張）` : "";
  setImageStatus(`已載入 ${images.length} 張截圖${note}`);
}

function removeImageAt(index) {
  const item = images[index];
  if (item) URL.revokeObjectURL(item.url);
  images.splice(index, 1);
  renderThumbs();
  setImageStatus(images.length ? `目前 ${images.length} 張截圖` : "尚未載入圖片");
}

function clearImages() {
  for (const item of images) URL.revokeObjectURL(item.url);
  images = [];
  renderThumbs();
  el.imageInput.value = "";
  setImageStatus("尚未載入圖片");
}

function imageFromPaste(event) {
  const items = Array.from(event.clipboardData?.items || []);
  const files = items
    .filter((item) => item.type.startsWith("image/"))
    .map((item) => item.getAsFile())
    .filter(Boolean);
  if (!files.length) return;
  event.preventDefault();
  addImages(files);
}

async function postAnalyze(text, withLlm) {
  const url = withLlm ? "/api/analyze" : "/api/analyze?llm=0";
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, mode: currentMode || "offline", geminiKey })
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "分析失敗");
  return data;
}

async function analyze() {
  if (!currentMode) {
    openModeModal();
    return;
  }
  if (currentMode === "online" && !geminiKey) {
    showError("請先輸入 Gemini API key。");
    openModeModal();
    return;
  }

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
  const llmLabel = currentMode === "online" ? "Gemini 研判中" : "4B LLM 研判中";

  try {
    if (shouldUseLlm()) {
      // 先用規則引擎即時回應，讓報告立刻更新；LLM 研判完再覆蓋。
      const fast = await postAnalyze(text, false);
      if (stale()) return;
      renderResult(fast, { llmPending: true });
      setServerStatus(`即時結果已更新 · ${llmLabel}`, "busy");

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
  addImages(event.target.files);
});

el.clearImageButton.addEventListener("click", clearImages);
el.ocrButton.addEventListener("click", recognizeImage);
el.qrButton.addEventListener("click", runQrScan);
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
  addImages(event.dataTransfer?.files);
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
initModeModal();
initKbModal();
openModeModal();   // 載入時請使用者先選離線/線上模式
checkHealth();
