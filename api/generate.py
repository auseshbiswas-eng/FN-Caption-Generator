from http.server import BaseHTTPRequestHandler
import json, os, urllib.request, urllib.error

_KEY = os.environ.get("OPENAI_API_KEY") or \
    "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"

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
        except: self._j({"error":"Invalid JSON"},400); return

        if not _KEY: self._j({"error":"No API key"},401); return

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(_to_oai(body)).encode(),
            headers={"Content-Type":"application/json","Authorization":f"Bearer {_KEY}"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                res = json.loads(r.read())
            text = res.get("choices",[{}])[0].get("message",{}).get("content","")
            self._j({"content":[{"type":"text","text":text}]})
        except urllib.error.HTTPError as e:
            raw_e = e.read().decode("utf-8","replace")
            try: eb = json.loads(raw_e)
            except: eb = {"message":raw_e}
            self._j({"error":eb}, e.code)
        except Exception as e:
            self._j({"error":str(e)},500)

    def _j(self, data, status=200):
        b = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",len(b))
        self._cors(); self.end_headers(); self.wfile.write(b)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")

    def log_message(self,*a): pass
