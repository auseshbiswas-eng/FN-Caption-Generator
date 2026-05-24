# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running Locally

```bash
python3 app.py
# Server runs on http://localhost:8080
```

No dependencies to install — the backend uses Python stdlib only (`urllib`, `json`, `http.server`, `socketserver`).

**Required environment variable:**
```bash
export fn_caption_api=sk-ant-...   # or ANTHROPIC_API_KEY
```

The key is checked in this order: `fn_caption_api` → `ANTHROPIC_API_KEY` → user-supplied via UI → `/api/key` POST.

## Deployment

```bash
vercel deploy
```

Vercel auto-deploys Python files in `/api/` as serverless functions. The `vercel.json` rewrites all non-`/api/` routes to `index.html` for SPA routing.

## Architecture

This is a minimal, zero-dependency stack:

- **Frontend:** Single `index.html` (~1,900 lines) — vanilla HTML/CSS/JS, no build step
- **Backend (local):** `app.py` — Python stdlib HTTP server on port 8080, proxies requests to Anthropic API
- **Backend (Vercel):** `/api/generate.py`, `/api/stream.py`, `/api/key.py` — serverless function equivalents of `app.py`'s routes

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/stream` | POST | Streaming caption generation (SSE, `text/event-stream`) |
| `/api/generate` | POST | Non-streaming generation (returns full JSON) |
| `/api/key` | POST | Update API key at runtime |

All endpoints accept `{ model, max_tokens, system, messages }` matching the Anthropic messages API. Model names are remapped: `gpt-4o` → `claude-sonnet-4-5`, `gpt-4o-mini` → `claude-haiku-4-5`.

### Frontend State & Features

The frontend manages state via a single `STATE` object. `localStorage` persists: `fn_apikey`, `fn_brand_voice`, `fn_bv_fname`.

Three main features, each in its own sidebar panel:

1. **Captions** — Text input → streaming caption via `/api/stream`
2. **Image Captions** — Base64 image upload → vision caption via `/api/stream`
3. **Translations** — Caption text → JSON with keys `it/fr/es/ar/pt` via `/api/generate`

Prompts are built by `buildCaptionPrompt()`, `buildImageCaptionPrompt()`, and `buildTranslatePrompt()`. All prompts embed the FundedNext brand voice guide, which is hardcoded in `index.html` but can be overridden by user upload (stored in `STATE.brandVoice`).

### Streaming Implementation

`/api/stream` returns Server-Sent Events. The client reads chunks with a `ReadableStream` reader, parses `data: {...}\n\n` lines, and extracts `delta.text` from `content_block_delta` events. The stream ends with `data: [DONE]`.

Local `app.py` filters and re-emits Anthropic's native SSE stream. Vercel `stream.py` does the same inside a serverless handler.

## Key Constraints

- Max request body: 20 MB (for base64 images; max image file size enforced client-side at 5 MB)
- Streaming timeout: 120s; non-streaming timeout: 90s
- CORS is open (`Access-Control-Allow-Origin: *`) — this is intentional for the single-user API key model
- No database — all persistence is `localStorage` or in-memory server state (resets on restart)
