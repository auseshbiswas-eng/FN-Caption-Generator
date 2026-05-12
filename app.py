#!/usr/bin/env python3
"""
FundedNext AI Caption Generator — Python Server (OpenAI backend)
Serves the dashboard UI and proxies calls to the OpenAI API.

Usage:
    python3 app.py
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

_DEFAULT_API_KEY = "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"

# Map legacy Anthropic model names → OpenAI equivalents
MODEL_MAP = {
    "claude-sonnet-4-6":        "gpt-4o",
    "claude-haiku-4-5-20251001": "gpt-4o-mini",
    "gpt-4o":                   "gpt-4o",
    "gpt-4o-mini":              "gpt-4o-mini",
}


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    api_key = os.environ.get("OPENAI_API_KEY", "") or _DEFAULT_API_KEY

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
    #  Request transformation: Anthropic-style body → OpenAI format       #
    # ------------------------------------------------------------------ #
    def _to_openai(self, body: dict, streaming: bool) -> dict:
        oai_messages = []

        if "system" in body:
            oai_messages.append({"role": "system", "content": body["system"]})

        for msg in body.get("messages", []):
            role = msg.get("role", "user")
            content = msg.get("content")

            if isinstance(content, list):
                # Multimodal: convert Anthropic image blocks → OpenAI image_url blocks
                oai_content = []
                for block in content:
                    if block.get("type") == "image":
                        src = block.get("source", {})
                        if src.get("type") == "base64":
                            oai_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{src['media_type']};base64,{src['data']}"
                                },
                            })
                    elif block.get("type") == "text":
                        oai_content.append({"type": "text", "text": block.get("text", "")})
                oai_messages.append({"role": role, "content": oai_content})
            else:
                oai_messages.append({"role": role, "content": content})

        model = MODEL_MAP.get(body.get("model", "gpt-4o"), "gpt-4o")

        oai_body = {
            "model": model,
            "messages": oai_messages,
            "stream": streaming,
        }
        if "max_tokens" in body:
            oai_body["max_tokens"] = body["max_tokens"]

        return oai_body

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

        oai_body = self._to_openai(body, streaming)
        payload = json.dumps(oai_body).encode("utf-8")

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
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
                        try:
                            chunk = json.loads(data_str)
                            text = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if text:
                                # Emit in Anthropic-compatible SSE format (client parses delta.text)
                                evt = json.dumps({
                                    "type": "content_block_delta",
                                    "delta": {"type": "text_delta", "text": text},
                                })
                                self.wfile.write(f"data: {evt}\n\n".encode("utf-8"))
                                self.wfile.flush()
                        except Exception:
                            pass
            else:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    result = json.loads(resp.read())
                # Convert OpenAI response → Anthropic-style shape the client JS expects
                content = (
                    result.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                self._send_json({"content": [{"type": "text", "text": content}]})

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
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
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
