"""Vercel serverless function: POST /api/stream
Calls OpenAI non-streaming, then emits the full text as SSE events so the
client's existing SSE parser works without any changes.
"""
import json
import sys
import os
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from _common import OPENAI_API_KEY, to_openai, openai_request, cors_headers

from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in cors_headers().items():
            self.send_header(k, v)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            self._sse_error("Invalid JSON body")
            return

        api_key = OPENAI_API_KEY
        if not api_key:
            self._sse_error("No OpenAI API key configured on server.")
            return

        # Call OpenAI non-streaming (Vercel buffers SSE anyway)
        oai_body = to_openai(body, streaming=False)
        req = openai_request(oai_body, api_key)

        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                result = json.loads(resp.read())
            text = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            self._sse_response(text)

        except urllib.error.HTTPError as exc:
            raw_err = exc.read().decode("utf-8", errors="replace")
            try:
                err_body = json.loads(raw_err)
                msg = (
                    err_body.get("error", {}).get("message")
                    or err_body.get("message")
                    or raw_err
                )
            except Exception:
                msg = raw_err
            self._sse_error(msg)

        except Exception as exc:
            self._sse_error(str(exc))

    def _sse_response(self, text: str):
        """Emit the full text as one SSE event + [DONE] in Anthropic-compat format."""
        evt = json.dumps({
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": text},
        })
        payload = f"data: {evt}\n\ndata: [DONE]\n\n".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", len(payload))
        for k, v in cors_headers().items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _sse_error(self, message: str):
        err_evt = json.dumps({"error": message})
        payload = f"data: {err_evt}\n\ndata: [DONE]\n\n".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", len(payload))
        for k, v in cors_headers().items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass
