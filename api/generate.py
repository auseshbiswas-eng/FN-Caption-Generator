"""Vercel serverless function: POST /api/generate"""
import json
import sys
import os
import urllib.error

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
            self._json({"error": "Invalid JSON body"}, 400)
            return

        api_key = OPENAI_API_KEY
        if not api_key:
            self._json({"error": "No OpenAI API key configured on server."}, 401)
            return

        oai_body = to_openai(body, streaming=False)
        req = openai_request(oai_body, api_key)

        try:
            import urllib.request
            with urllib.request.urlopen(req, timeout=90) as resp:
                result = json.loads(resp.read())
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            self._json({"content": [{"type": "text", "text": content}]})

        except urllib.error.HTTPError as exc:
            raw_err = exc.read().decode("utf-8", errors="replace")
            try:
                err_body = json.loads(raw_err)
            except Exception:
                err_body = {"message": raw_err}
            self._json({"error": err_body}, exc.code)

        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        for k, v in cors_headers().items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass
