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
        except: self._sse_err("Invalid JSON"); return

        if not _KEY: self._sse_err("No OPENAI_API_KEY set on server."); return

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
            self._sse_ok(text)
        except urllib.error.HTTPError as e:
            raw_e = e.read().decode("utf-8", "replace")
            try: msg = json.loads(raw_e).get("error", {}).get("message", raw_e)
            except: msg = raw_e
            self._sse_err(msg)
        except Exception as e:
            self._sse_err(str(e))

    def _sse_ok(self, text):
        evt = json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}})
        payload = f"data: {evt}\n\ndata: [DONE]\n\n".encode()
        self._sse_write(payload)

    def _sse_err(self, msg):
        payload = f"data: {json.dumps({'error': msg})}\n\ndata: [DONE]\n\n".encode()
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
