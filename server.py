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

MAX_BODY_BYTES = 256 * 1024  # 請求大小上限，防呆
MAX_TEXT_CHARS = 8000  # 分析文字長度上限


def write_log(message):
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


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
        return super().do_GET()

    def do_POST(self):
        raw_path, _, query = self.path.partition("?")
        path = unquote(raw_path)
        if path not in {"/api/analyze", "/api/check-link"}:
            self.send_error(404, "Not Found")
            return
        # ?llm=0 → 只跑規則引擎（即時回應，供前端漸進式渲染）。
        params = parse_qs(query)
        use_llm = params.get("llm", ["1"])[0].lower() not in {"0", "false", "no", "off"}

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Content-Length 無效。"}, status=400)
            return
        if length < 0:
            # 負值會繞過下方上限檢查，且 rfile.read(負值) 會讀到 EOF 阻塞執行緒。
            self._send_json({"error": "Content-Length 無效。"}, status=400)
            return
        if length > MAX_BODY_BYTES:
            self._send_json({"error": "請求內容過大，請縮短文字。"}, status=413)
            return

        try:
            try:
                body = self.rfile.read(length).decode("utf-8")
            except UnicodeDecodeError:
                self._send_json({"error": "請求內容需為 UTF-8 JSON。"}, status=400)
                return
            payload = json.loads(body or "{}")
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
            result = demo.analyze(text, use_llm=use_llm)
            self._send_json(result)
        except json.JSONDecodeError:
            self._send_json({"error": "請求格式錯誤，需為 JSON。"}, status=400)
        except Exception as exc:
            write_log("analyze error: " + traceback.format_exc())
            print("[server] analyze error:", exc)
            self._send_json({"error": "伺服器內部錯誤，請稍後再試。"}, status=500)

    def _send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    # 雲端平台（如 Render）以環境變數 PORT 指定埠並需綁 0.0.0.0；本機維持 127.0.0.1。
    port = int(os.environ.get("PORT", "8765"))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    write_log(f"starting server root={ROOT}")
    server = ThreadingHTTPServer((host, port), ScamGuardHandler)
    write_log(f"listening http://{host}:{port}")
    print(f"二手交易 AI 防踩雷助理已啟動：http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        write_log(traceback.format_exc())
        raise
