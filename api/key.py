"""Vercel serverless function: POST /api/key
On Vercel the key lives in env — this endpoint just acknowledges the call
so the client's pingKey() succeeds and marks the connection as live.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from _common import cors_headers

from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in cors_headers().items():
            self.send_header(k, v)
        self.end_headers()

    def do_POST(self):
        self._json({"status": "ok", "set": True})

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
