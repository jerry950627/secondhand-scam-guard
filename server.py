from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import traceback
from urllib.parse import parse_qs, unquote


ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "app"
DEMO_PATH = ROOT / "src" / "scam_guard_demo.py"
LOG_PATH = ROOT / "server.log"

MAX_BODY_BYTES = 256 * 1024  # 文字請求大小上限，防呆
MAX_VLM_BYTES = 6 * 1024 * 1024  # /api/vlm 帶 base64 影像，放寬上限
MAX_VLM_IMAGES = 8  # /api/vlm 單次最多張數
MAX_TEXT_CHARS = 8000  # 分析文字長度上限
MAX_KEY_CHARS = 200  # Gemini API key 長度上限，防呆


def write_log(message):
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        # 寫 log 失敗（例如解壓到唯讀資料夾）不應讓伺服器崩潰。
        pass


def load_demo_module():
    spec = importlib.util.spec_from_file_location("scam_guard_demo", DEMO_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo = load_demo_module()


class ScamGuardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def log_message(self, format, *args):
        print("[server]", format % args)

    def end_headers(self):
        # 本機開發：關閉快取，改前端後普通重整即可生效，不必 Ctrl+F5。
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path in {"/", ""}:
            self.path = "/index.html"
        if self.path.split("?", 1)[0] == "/api/health":
            self._send_json({"status": "ok", "llm_available": demo._LLM_AVAILABLE})
            return
        if self.path.split("?", 1)[0] == "/api/knowledge-base":
            # 供前端「詐騙樣態圖鑑」瀏覽 16 類知識庫。
            self._send_json(demo.knowledge_base())
            return
        return super().do_GET()

    def do_POST(self):
        raw_path, _, query = self.path.partition("?")
        path = unquote(raw_path)
        if path not in {"/api/analyze", "/api/check-link", "/api/vlm"}:
            self.send_error(404, "Not Found")
            return
        # ?llm=0 → 只跑規則引擎（即時回應，供前端漸進式渲染）。
        params = parse_qs(query)
        use_llm = params.get("llm", ["1"])[0].lower() not in {"0", "false", "no", "off"}

        # /api/vlm 會帶 base64 影像，放寬上限；其餘維持文字小上限。
        max_bytes = MAX_VLM_BYTES if path == "/api/vlm" else MAX_BODY_BYTES
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Content-Length 無效。"}, status=400)
            return
        if length < 0:
            # 負值會繞過下方上限檢查，且 rfile.read(負值) 會讀到 EOF 阻塞執行緒。
            self._send_json({"error": "Content-Length 無效。"}, status=400)
            return
        if length > max_bytes:
            self._send_json({"error": "請求內容過大，請縮小圖片或縮短文字。"}, status=413)
            return

        try:
            try:
                body = self.rfile.read(length).decode("utf-8")
            except UnicodeDecodeError:
                self._send_json({"error": "請求內容需為 UTF-8 JSON。"}, status=400)
                return
            payload = json.loads(body or "{}")

            if path == "/api/vlm":
                # 線上版 VLM：截圖交給 Gemini 逐字轉錄（不走文字驗證流程）。
                self._handle_vlm(payload)
                return

            text = str(payload.get("text", "")).strip()
            if not text:
                self._send_json({"error": "請先貼上交易貼文、私訊內容，或 VLM/OCR 抽出的截圖文字。"}, status=400)
                return
            if len(text) > MAX_TEXT_CHARS:
                self._send_json({"error": f"文字長度超過上限（{MAX_TEXT_CHARS} 字），請縮短後再試。"}, status=400)
                return

            if path == "/api/check-link":
                # 輕量：只抽網址/電話查黑名單與啟發式，不跑規則/LLM。
                self._send_json(demo.check_text(text))
                return

            # 離線/線上模式 + 每次請求帶入的 Gemini key（key 不落地、不記錄）。
            mode = str(payload.get("mode", "offline")).strip().lower()
            if mode not in {"offline", "online"}:
                mode = "offline"
            gemini_api_key = str(payload.get("geminiKey", "")).strip()
            if len(gemini_api_key) > MAX_KEY_CHARS:
                gemini_api_key = ""
            result = demo.analyze(text, use_llm=use_llm, mode=mode, gemini_api_key=gemini_api_key)
            self._send_json(result)
        except json.JSONDecodeError:
            self._send_json({"error": "請求格式錯誤，需為 JSON。"}, status=400)
        except Exception as exc:
            write_log("analyze error: " + traceback.format_exc())
            print("[server] analyze error:", exc)
            self._send_json({"error": "伺服器內部錯誤，請稍後再試。"}, status=500)

    def _handle_vlm(self, payload):
        # 接受多張（images 陣列）或單張（image 字串，保留相容）。
        raw = payload.get("images")
        if isinstance(raw, list):
            urls = [str(x).strip() for x in raw]
        else:
            urls = [str(payload.get("image", "")).strip()]
        urls = [u for u in urls if u]
        if not urls or len(urls) > MAX_VLM_IMAGES or not all(u.startswith("data:image/") for u in urls):
            self._send_json(
                {"error": f"需提供 1～{MAX_VLM_IMAGES} 張 data:image/... 的截圖。"}, status=400
            )
            return
        gemini_api_key = str(payload.get("geminiKey", "")).strip()
        if not gemini_api_key or len(gemini_api_key) > MAX_KEY_CHARS:
            self._send_json({"error": "請先輸入有效的 Gemini API key。"}, status=400)
            return
        text = demo.vlm_transcribe(urls, gemini_api_key)
        if not text:
            self._send_json({"error": "Gemini 看圖失敗，請確認金鑰或改用本機 OCR。"}, status=502)
            return
        self._send_json({"text": text})

    def _send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    # 預設本機 127.0.0.1:8765；若 8765 被占用或想對外，可用環境變數 PORT 指定
    # （設了 PORT 會綁 0.0.0.0 方便區網/通道存取）。
    port = int(os.environ.get("PORT", "8765"))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    write_log(f"starting server root={ROOT}")
    try:
        server = ThreadingHTTPServer((host, port), ScamGuardHandler)
    except OSError as exc:
        # 最常見：連接埠被占用。給清楚的提示，而不是丟一串 traceback。
        print(f"無法在 {host}:{port} 啟動（{exc}）。", flush=True)
        print(f"連接埠 {port} 可能已被占用；換一個埠再試，例如：", flush=True)
        print('  PowerShell:  $env:PORT=9000; python server.py', flush=True)
        print('  macOS/Linux: PORT=9000 python3 server.py', flush=True)
        raise SystemExit(1)
    write_log(f"listening http://{host}:{port}")
    print(f"二手交易 AI 防踩雷助理已啟動：http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        write_log(traceback.format_exc())
        raise
