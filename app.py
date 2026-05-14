#!/usr/bin/env python3
"""
FundedNext AI Caption Generator — Python Server (Anthropic Claude backend)
Serves the dashboard UI and proxies calls to the Anthropic API.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python3 app.py
"""

import http.server
import json
import os
import urllib.request
import urllib.error
import socketserver
import sys
from pathlib import Path

PORT = int(os.environ.get("PORT", 8080))
BASE_DIR = Path(__file__).parent
MAX_BODY = 20 * 1024 * 1024  # 20 MB — allows base64-encoded images

MODEL_MAP = {
    "gpt-4o":                    "claude-sonnet-4-5",
    "gpt-4o-mini":               "claude-haiku-4-5",
    "claude-sonnet-4-6":         "claude-sonnet-4-5",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5",
}


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._serve_file(BASE_DIR / "index.html", "text/html; charset=utf-8")
        elif path.startswith("/static/"):
            file_path = BASE_DIR / path.lstrip("/")
            if file_path.exists():
                self._serve_file(file_path, self._mime(file_path.suffix))
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > MAX_BODY:
            self._send_json({"error": "Request body too large (max 20 MB)"}, 413)
            return

        raw = self.rfile.read(content_length)
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON body"}, 400)
            return

        if self.path == "/api/key":
            key = body.get("key", "").strip()
            DashboardHandler.api_key = key
            self._send_json({"status": "ok", "set": bool(key)})

        elif self.path == "/api/generate":
            self._anthropic(body, streaming=False)

        elif self.path == "/api/stream":
            self._anthropic(body, streaming=True)

        else:
            self.send_error(404)

    # ------------------------------------------------------------------ #
    #  Anthropic proxy                                                     #
    # ------------------------------------------------------------------ #
    def _anthropic(self, body: dict, streaming: bool):
        api_key = DashboardHandler.api_key
        if not api_key:
            self._send_json(
                {"error": "No API key set. Click the 🔑 button and enter your Anthropic API key."},
                401,
            )
            return

        # Remap model and set stream flag
        body["model"] = MODEL_MAP.get(body.get("model", ""), "claude-sonnet-4-5")
        body["stream"] = streaming

        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
            },
        )

        try:
            if streaming:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self._cors_headers()
                self.end_headers()

                with urllib.request.urlopen(req, timeout=120) as resp:
                    while True:
                        line = resp.readline()
                        if not line:
                            break
                        line_str = line.decode("utf-8", errors="replace").rstrip()
                        if not line_str.startswith("data: "):
                            continue
                        data_str = line_str[6:].strip()
                        if data_str in ("[DONE]", ""):
                            continue
                        try:
                            chunk = json.loads(data_str)
                            if chunk.get("type") == "content_block_delta":
                                # Already in the right format — pass through
                                self.wfile.write(f"data: {data_str}\n\n".encode("utf-8"))
                                self.wfile.flush()
                            elif chunk.get("type") == "message_stop":
                                self.wfile.write(b"data: [DONE]\n\n")
                                self.wfile.flush()
                                break
                        except Exception:
                            pass
            else:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    result = json.loads(resp.read())
                # Anthropic response already has content[{type,text}] — pass through
                self._send_json(result)

        except urllib.error.HTTPError as exc:
            raw_err = exc.read().decode("utf-8", errors="replace")
            try:
                err_body = json.loads(raw_err)
            except Exception:
                err_body = {"message": raw_err}
            self._send_json({"error": err_body}, exc.code)

        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #
    def _serve_file(self, path: Path, mime: str):
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404, f"{path.name} not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", len(content))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    @staticmethod
    def _mime(ext: str) -> str:
        return {
            ".html": "text/html; charset=utf-8",
            ".css":  "text/css",
            ".js":   "application/javascript",
            ".json": "application/json",
            ".png":  "image/png",
            ".jpg":  "image/jpeg",
            ".svg":  "image/svg+xml",
            ".ico":  "image/x-icon",
            ".woff2":"font/woff2",
        }.get(ext.lower(), "application/octet-stream")

    def log_message(self, fmt, *args):
        code = str(args[1]) if len(args) > 1 else "?"
        if code.startswith(("4", "5")):
            print(f"  ⚠  {self.address_string()} — {fmt % args}", file=sys.stderr)


def main():
    banner = f"""
╔══════════════════════════════════════════════════════╗
║   ✍  FundedNext AI Caption Generator  v1.0          ║
╠══════════════════════════════════════════════════════╣
║   URL  →  http://localhost:{PORT:<24}║
║   Stop →  Ctrl + C                                   ║
╚══════════════════════════════════════════════════════╝"""
    print(banner)

    if DashboardHandler.api_key:
        masked = DashboardHandler.api_key[:8] + "..." + DashboardHandler.api_key[-4:]
        print(f"  ✓  Anthropic API key loaded from environment  ({masked})")
    else:
        print("  ⚠  No ANTHROPIC_API_KEY in environment.")
        print("     Open the dashboard and click 🔑 to enter your key.")

    print()

    class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with ThreadedServer(("", PORT), DashboardHandler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n\n  Shutting down. Goodbye!\n")


if __name__ == "__main__":
    main()
