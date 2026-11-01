# Legal Document Assistant — Telegram Bot

A private Telegram bot for drafting legal documents: describe a situation in
plain language (by text, voice, or a photo of a document) and it prepares PDF
drafts with suggested legal references for a person to verify.

Built on **[aiogram 3](https://docs.aiogram.dev/)** (async), it combines a
multi-provider LLM layer, on-device speech recognition, document-image OCR/vision,
an encrypted personal document vault, and GOST-styled HTML→PDF rendering.

> This is a sanitized portfolio copy. All secrets, personal data, real user IDs,
> databases and the user vault have been removed. Configuration is entirely
> environment-based — see [`.env.example`](.env.example).

---

## Highlights

- **Conversational drafting** — free-text requests are classified (draft a doc /
  legal consultation / edit profile / history) and turned into one or more
  documents. Missing facts trigger a minimal clarifying-question loop before a
  draft is produced.
- **Draft → approve → finalize flow** — every generated document is first sent as
  a *draft* PDF with inline buttons (Approve / Edit / Cancel). On approval the
  user's stored profile is merged into the placeholders and the final PDF is
  produced and archived to history.
- **Multi-provider LLM fallback** — a single async `chat()` router walks an
  ordered chain of providers (OpenAI, Anthropic, OpenRouter, Groq, Gemini, plus a
  local browser-proxy fallback) and returns the first success, so a single
  provider outage or rate-limit never takes the bot down.
- **Multimodal I/O**
  - **Voice in** — voice notes are transcribed locally with `faster-whisper`
    (CPU, int8), fed through the normal text flow, and answers can be spoken back.
  - **Text-to-speech** — replies are optionally voiced with `edge-tts`.
  - **Vision / OCR** — photos and image-files of documents are recognized by a
    vision model that classifies the document type and extracts structured fields,
    which can auto-populate the user's profile.
- **Encrypted personal vault** — uploaded document scans are encrypted at rest
  with **AES-256-GCM** (per-file random nonce, `tg_id` as associated data),
  stored under per-user `0700` directories, with byte-level and semantic
  de-duplication.
- **GOST-styled PDF export** — HTML documents are rendered to A4 PDFs with
  WeasyPrint using margins/typography aligned to GOST R 7.0.97-2016.
- **Private by design** — a whitelist middleware restricts the bot to an owner
  and an explicit allow-list of Telegram IDs.

---

## Architecture

The codebase is split into a thin **handlers/** layer (Telegram I/O, routing,
FSM, conversation state) over a reusable **services/** layer (all business logic,
provider-agnostic and independently testable).

```
main.py            Entry point: builds Bot/Dispatcher, wires middleware + router
middleware.py      WhitelistMiddleware — access control for messages & callbacks
config.py          Env-based config, LLM provider chains, PDF page style
db.py              Async SQLite: profiles, history, dialog state, vault, pending docs

handlers/          Telegram-facing layer (aiogram Routers)
├─ start.py          /start, /help, main keyboard
├─ profile.py        FSM-driven profile editor (/edit_profile) + /profile view
├─ dialog.py         Core flow: classify → consult or generate → draft → approve
├─ vault.py          Photo/document intake, OCR, encrypted storage, /vault /find
├─ voice.py          Voice notes → STT → dialog flow → optional TTS reply
└─ history.py        /history and per-document retrieval

services/          Business logic (no Telegram dependency)
├─ llm_providers.py  Unified async multi-provider chat() with fallback chain
├─ llm.py            Legal "brain": intent routing, generation, consultation
├─ doc_brain.py      Request → generated PDFs orchestration
├─ vision.py         Document-image recognition & field extraction
├─ stt.py            Local speech-to-text (faster-whisper)
├─ tts.py            Text-to-speech (edge-tts)
├─ vault.py          AES-256-GCM encrypted file storage + de-duplication
└─ pdf.py            HTML/Jinja2 → PDF (WeasyPrint, GOST styling)
```

### Provider fallback chain

Provider chains are declarative lists of `(provider, model)` tuples in
`config.py` — separate chains for high-quality generation (`LLM_CHAIN`), fast
routing (`LLM_CHAIN_FAST`), and vision (`VISION_CHAIN`). `llm_providers.chat()`
normalizes OpenAI-style and Anthropic-style message/image formats behind one
interface and tries each entry in order until one succeeds:

```python
LLM_CHAIN_FAST = [
    ("openai", "gpt-4.1-mini"),
    ("gemini_browser", "gemini-2.0-flash"),
    ("openai", "gpt-4o-mini"),
    ("groq", "llama-3.3-70b-versatile"),
]
```

Clients are only instantiated for providers whose API key is present, and any
provider that errors is logged and skipped — the chain degrades gracefully.

### Encrypted vault design

Each uploaded scan is encrypted with a single AES-256-GCM key (base64 in
`VAULT_KEY`, supplied by the operator). The ciphertext is `nonce || ct`,
with a fresh 12-byte nonce per file and the owner's `tg_id` bound as GCM
associated data, so a file can only be decrypted in the context of its owner.
Files live under per-user directories (`0700`) with `0600` permissions, indexed
in SQLite alongside SHA-256 (byte-level dedup) and extracted OCR fields
(semantic dedup, e.g. the same passport re-photographed).

---

## Tech stack

| Area          | Tech |
|---------------|------|
| Bot framework | aiogram 3 (asyncio) |
| LLMs          | OpenAI, Anthropic, OpenRouter, Groq, Gemini (+ local proxy) |
| Speech-to-text| faster-whisper (local, CPU int8) |
| Text-to-speech| edge-tts |
| Vision/OCR    | vision-capable LLMs via the provider chain |
| PDF           | WeasyPrint + Jinja2 |
| Storage       | SQLite (aiosqlite) |
| Crypto        | cryptography (AES-256-GCM) |

---

## Getting started

```bash
# 1. Install dependencies (Python 3.11+ recommended)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
#    System deps: ffmpeg (STT audio conversion) and the WeasyPrint
#    native libraries (pango, cairo, gdk-pixbuf).

# 2. Configure
cp .env.example .env
#    Fill in BOT_TOKEN, OWNER_TG_ID, VAULT_KEY, and at least one LLM provider key.
#    Generate VAULT_KEY once with: python -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
#    Keep .env private: chmod 600 .env

# 3. Run
python main.py
```

On first launch the SQLite schema is created automatically. The application
refuses to start without a valid `VAULT_KEY`; keep the same key across restarts
or previously encrypted documents cannot be read.

The vault-key checks run with `python -m unittest discover -s tests` after
installing the dependencies.

---

## Notes

- **Legal disclaimer** — generated documents are drafting aids, not legal advice;
  they should be reviewed before use.
- Localized for the Russian legal domain (document types, GOST styling, statute
  references); the architecture is language- and jurisdiction-agnostic.
