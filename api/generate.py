from http.server import BaseHTTPRequestHandler
import json, os, urllib.request, urllib.error

_KEY = os.environ.get("fn_caption_api") or os.environ.get("OPENAI_API_KEY", "")


def _to_openai_body(body):
    """Convert Anthropic-format request to OpenAI chat completions format."""
    oai = {
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


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try: body = json.loads(raw) if raw else {}
        except: self._j({"error": "Invalid JSON"}, 400); return

        if not _KEY: self._j({"error": "No OPENAI_API_KEY set on server."}, 401); return

        oai_body = _to_openai_body(body)
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(oai_body).encode(),
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {_KEY}",
            })
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                result = json.loads(r.read())
            text = result["choices"][0]["message"]["content"]
            # Return in Anthropic format so the frontend parser stays unchanged
            self._j({"content": [{"type": "text", "text": text}]})
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
