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
        except: self._j({"error": "Invalid JSON"}, 400); return

        if not _KEY: self._j({"error": "No ANTHROPIC_API_KEY set on server."}, 401); return

        # Remap model name, remove stream flag
        body["model"] = _MODEL_MAP.get(body.get("model", ""), "claude-sonnet-4-5")
        body.pop("stream", None)

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type":    "application/json",
                "x-api-key":       _KEY,
                "anthropic-version": "2023-06-01",
            })
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                result = json.loads(r.read())
            # Anthropic response already has content[0].text — pass through directly
            self._j(result)
        except urllib.error.HTTPError as e:
            raw_e = e.read().decode("utf-8", "replace")
            try: eb = json.loads(raw_e)
            except: eb = {"message": raw_e}
            self._j({"error": eb}, e.code)
        except Exception as e:
            self._j({"error": str(e)}, 500)

    def _j(self, data, status=200):
        b = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(b))
        self._cors(); self.end_headers(); self.wfile.write(b)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, *a): pass
