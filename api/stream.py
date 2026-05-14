from http.server import BaseHTTPRequestHandler
import json, os, urllib.request, urllib.error

_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

_MODEL_MAP = {
    "gpt-4o":                    "claude-sonnet-4-5",
    "gpt-4o-mini":               "claude-haiku-4-5",
    "claude-sonnet-4-6":         "claude-sonnet-4-5",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5",
}

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try: body = json.loads(raw) if raw else {}
        except: self._sse_err("Invalid JSON"); return

        if not _KEY: self._sse_err("No ANTHROPIC_API_KEY set on server."); return

        body["model"] = _MODEL_MAP.get(body.get("model", ""), "claude-sonnet-4-5")
        body.pop("stream", None)

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         _KEY,
                "anthropic-version": "2023-06-01",
            })
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                result = json.loads(r.read())
            text = result.get("content", [{}])[0].get("text", "")
            self._sse_ok(text)
        except urllib.error.HTTPError as e:
            raw_e = e.read().decode("utf-8", "replace")
            try: msg = json.loads(raw_e).get("error", {}).get("message", raw_e)
            except: msg = raw_e
            self._sse_err(msg)
        except Exception as e:
            self._sse_err(str(e))

    def _sse_ok(self, text):
        evt = json.dumps({"type":"content_block_delta","delta":{"type":"text_delta","text":text}})
        payload = f"data: {evt}\n\ndata: [DONE]\n\n".encode()
        self._sse_write(payload)

    def _sse_err(self, msg):
        payload = f"data: {json.dumps({'error':msg})}\n\ndata: [DONE]\n\n".encode()
        self._sse_write(payload)

    def _sse_write(self, payload):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", len(payload))
        self._cors(); self.end_headers(); self.wfile.write(payload)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, *a): pass
