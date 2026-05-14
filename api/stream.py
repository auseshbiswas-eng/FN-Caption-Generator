from http.server import BaseHTTPRequestHandler
import json, os, urllib.request, urllib.error

_KEY = os.environ.get("OPENAI_API_KEY", "")

_MODEL = {"claude-sonnet-4-6":"gpt-4o","claude-haiku-4-5-20251001":"gpt-4o-mini",
          "gpt-4o":"gpt-4o","gpt-4o-mini":"gpt-4o-mini"}

def _to_oai(body):
    msgs = []
    if "system" in body:
        msgs.append({"role":"system","content":body["system"]})
    for m in body.get("messages",[]):
        c = m.get("content")
        if isinstance(c, list):
            oc = []
            for b in c:
                if b.get("type")=="image":
                    s=b.get("source",{})
                    if s.get("type")=="base64":
                        oc.append({"type":"image_url","image_url":{"url":f"data:{s['media_type']};base64,{s['data']}"}})
                elif b.get("type")=="text":
                    oc.append({"type":"text","text":b.get("text","")})
            msgs.append({"role":m.get("role","user"),"content":oc})
        else:
            msgs.append({"role":m.get("role","user"),"content":c})
    ob = {"model":_MODEL.get(body.get("model","gpt-4o"),"gpt-4o"),"messages":msgs,"stream":False}
    if "max_tokens" in body: ob["max_tokens"]=body["max_tokens"]
    return ob

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length",0)))
        try: body = json.loads(raw) if raw else {}
        except: self._sse_err("Invalid JSON"); return

        if not _KEY: self._sse_err("No API key configured"); return

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(_to_oai(body)).encode(),
            headers={"Content-Type":"application/json","Authorization":f"Bearer {_KEY}"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                res = json.loads(r.read())
            text = res.get("choices",[{}])[0].get("message",{}).get("content","")
            self._sse_ok(text)
        except urllib.error.HTTPError as e:
            raw_e = e.read().decode("utf-8","replace")
            try: msg = json.loads(raw_e).get("error",{}).get("message", raw_e)
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
        self.send_header("Content-Type","text/event-stream")
        self.send_header("Cache-Control","no-cache")
        self.send_header("Content-Length",len(payload))
        self._cors(); self.end_headers(); self.wfile.write(payload)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")

    def log_message(self,*a): pass
