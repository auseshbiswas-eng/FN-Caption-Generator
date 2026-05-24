#!/usr/bin/env python3
"""
FundedNext AI Caption Generator — Python Server (OpenAI backend)
Serves the dashboard UI and proxies calls to the OpenAI API.

Usage:
    OPENAI_API_KEY=sk-proj-... python3 app.py
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


def _to_openai_body(body: dict) -> dict:
    """Convert Anthropic-format request to OpenAI chat completions format."""
    oai: dict = {
        "model": body.get("model", "gpt-4o"),
        "max_tokens": body.get("max_tokens", 1024),
    }
    messages = []
    if body.get("system"):
        messages.append({"role": "system", "content": body["system"]})
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
        elif isinstance(content, list):
            oai_content = []
            for block in content:
                if block.get("type") == "text":
                    oai_content.append({"type": "text", "text": block["text"]})
                elif block.get("type") == "image":
                    src = block.get("source", {})
                    if src.get("type") == "base64":
                        mt = src.get("media_type", "image/jpeg")
                        oai_content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{mt};base64,{src.get('data', '')}"}
                        })
            messages.append({"role": role, "content": oai_content})
    oai["messages"] = messages
    return oai


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    api_key = os.environ.get("fn_caption_api") or os.environ.get("OPENAI_API_KEY", "")

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
            self._openai(body, streaming=False)

        elif self.path == "/api/stream":
            self._openai(body, streaming=True)

        else:
            self.send_error(404)

    # ------------------------------------------------------------------ #
    #  OpenAI proxy                                                        #
    # ------------------------------------------------------------------ #
    def _openai(self, body: dict, streaming: bool):
        api_key = DashboardHandler.api_key
        if not api_key:
            self._send_json(
                {"error": "No API key set. Click the 🔑 button and enter your OpenAI API key."},
                401,
            )
            return

        oai_body = _to_openai_body(body)
        oai_body["stream"] = streaming

        payload = json.dumps(oai_body).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {api_key}",
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
                        if data_str == "[DONE]":
                            self.wfile.write(b"data: [DONE]\n\n")
                            self.wfile.flush()
                            break
                        if not data_str:
                            continue
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                evt = json.dumps({
                                    "type": "content_block_delta",
                                    "delta": {"type": "text_delta", "text": text}
                                })
                                self.wfile.write(f"data: {evt}\n\n".encode("utf-8"))
                                self.wfile.flush()
                        except Exception:
                            pass
            else:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    result = json.loads(resp.read())
                text = result["choices"][0]["message"]["content"]
                # Return in Anthropic format so the frontend parser stays unchanged
                self._send_json({"content": [{"type": "text", "text": text}]})

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
        print(f"  ✓  OpenAI API key loaded from environment  ({masked})")
    else:
        print("  ⚠  No OPENAI_API_KEY in environment.")
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
