"""Shared helpers for Vercel serverless functions."""
import json
import os
import urllib.request
import urllib.error

OPENAI_API_KEY = (
    os.environ.get("OPENAI_API_KEY", "")
    or "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"
)

MODEL_MAP = {
    "claude-sonnet-4-6":         "gpt-4o",
    "claude-haiku-4-5-20251001": "gpt-4o-mini",
    "gpt-4o":                    "gpt-4o",
    "gpt-4o-mini":               "gpt-4o-mini",
}


def to_openai(body: dict, streaming: bool) -> dict:
    oai_messages = []
    if "system" in body:
        oai_messages.append({"role": "system", "content": body["system"]})
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content")
        if isinstance(content, list):
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
    oai_body = {"model": model, "messages": oai_messages, "stream": streaming}
    if "max_tokens" in body:
        oai_body["max_tokens"] = body["max_tokens"]
    return oai_body


def openai_request(oai_body: dict, api_key: str):
    payload = json.dumps(oai_body).encode("utf-8")
    return urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )


def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }
