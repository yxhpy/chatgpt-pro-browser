# chatgpt-pro-browser

> Use your **already-logged-in ChatGPT (incl. Pro)** from the terminal by driving the real Chrome browser.

[![tests](https://img.shields.io/badge/tests-20%2F20%20pass-brightgreen)](TEST_REPORT.md)
[![platform](https://img.shields.io/badge/platform-macOS-lightgrey)](#prerequisites)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](requirements.txt)

`chatgpt-pro-browser` is a ZCode/Codex **skill** plus a reusable Python **harness** that lets you call ChatGPT (especially Pro models like **GPT-5 Pro / GPT-5.5 Pro**) from scripts, automation, or other agents — by operating the actual chatgpt.com web UI with your own logged-in session.

It is **not** a reverse-engineered API. Raw HTTP/cookie access to ChatGPT is blocked by Cloudflare (`cf-mitigated: challenge`, confirmed 403). This project decrypts Chrome's login cookies and injects them into a Playwright-controlled **real** Chrome, then drives the UI like a human would — prompts, file uploads, multi-turn conversations all work.

## Why

- You pay for ChatGPT Pro but the [official API](https://platform.openai.com) is metered separately and doesn't include Pro models.
- You want GPT-5 Pro / GPT-5.5 Pro from a script, agent, or HTTP endpoint.
- You tried raw-cookie HTTP and hit the Cloudflare wall.
- You tried cloning your Chrome profile and lost the login session.

## What works (verified, 20/20 tests passing)

| Capability | Status |
|---|---|
| Login reuse (Pro/Plus/Free) | ✅ |
| Single prompt → text reply | ✅ |
| File uploads: PNG, JPG, PDF, CSV, TXT, JSON, PY, MD, DOCX, XLSX | ✅ |
| Multi-file uploads (3-5 files, mixed types) | ✅ |
| Cross-file reasoning (e.g. sum values across files) | ✅ |
| Big inputs (132 KB file, 14 KB pasted prompt) | ✅ |
| Long outputs (2000+ words) | ✅ |
| Deep reasoning (GPT-5 Pro, multi-step math) | ✅ |
| Multi-turn conversation state | ✅ |

See [TEST_REPORT.md](TEST_REPORT.md) for the full matrix and timing data.

## Prerequisites

- **macOS** (uses the Keychain + Chrome's on-disk cookies).
- **Google Chrome** installed and used to log into [chatgpt.com](https://chatgpt.com) at least once.
- **Python 3.10+** with `playwright` and `cryptography`.
- A ChatGPT **Pro** subscription (for the Pro models; the harness also works on Plus/Free with `--no-pro`).

## Install

### One-line (recommended)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/yxhpy/chatgpt-pro-browser/main/install.sh)
```

This runs the prerequisites check, installs Python deps + Playwright Chromium, and symlinks the skill into `~/.agents/skills/` so ZCode discovers it.

### Manual

```bash
git clone https://github.com/yxhpy/chatgpt-pro-browser.git
cd chatgpt-pro-browser
bash install.sh           # or: bash install.sh --copy for a frozen snapshot
```

The first time you use it, macOS will show a Keychain dialog for **"Chrome Safe Storage"** — click **Allow** (or **Always Allow**). This is one-time and grants the decryption key.

## Quick start

### From the CLI

```bash
# Send one prompt, print the reply
python3 skills/chatgpt-pro-browser/scripts/ask.py "Write a haiku about SSH keys."

# Attach files
python3 skills/chatgpt-pro-browser/scripts/ask.py "Summarize this." -f report.pdf -f data.csv
```

### From Python

```python
import asyncio
from lib.harness import ChatGPTSession

async def main():
    async with ChatGPTSession(headless=False) as s:
        await s.ensure_pro()
        r = await s.ask("What model are you?")
        print(r.text)

        # upload + ask
        r = await s.ask("Summarize this PDF.", attachments=["report.pdf"])

        # multi-turn (same session keeps context)
        await s.ask("Now translate that to Chinese.")

asyncio.run(main())
```

### As an OpenAI-compatible HTTP endpoint

Wrap the harness in ~30 lines of FastAPI — see [skills/chatgpt-pro-browser/references/http-bridge.md](skills/chatgpt-pro-browser/references/http-bridge.md). Then point any OpenAI client at `OPENAI_BASE_URL=http://127.0.0.1:8787/v1`.

### As a ZCode/Codex skill

Once installed, just describe what you want in natural language — the skill auto-triggers:

> "用我登录的 ChatGPT Pro 总结这个 PDF"
> "Ask chatgpt pro to review my code"

## How it works

```
            macOS Keychain
       ┌──────────────────────┐
       │ "Chrome Safe Storage" │── PBKDF2-SHA1(saltysalt, 1003) ──► AES-128 key
       └──────────┬───────────┘
                  │
   ~/.../Chrome/  │
   Default/       ▼
   Cookies.sqlite ──► decrypt v10 cookie blobs (strip domain-binding prefix)
                  │   → session-token, _puid, cf_clearance, oai-sc, …
                  ▼
        Playwright ── channel="chrome"  (REAL Chrome binary — Cloudflare-safe)
        new_context ── ctx.add_cookies([...])
                  │
                  ▼
        page.goto("chatgpt.com/")  ── logged in (Pro), no CF challenge
                  │
                  ▼
        div.ProseMirror → keyboard.type() → Enter → wait for stop-button to vanish
                  │
                  ▼
        read assistant reply
```

Key technical points (full detail in [skills/chatgpt-pro-browser/references/pitfalls.md](skills/chatgpt-pro-browser/references/pitfalls.md)):

1. **Why decrypt + inject, not clone the profile?** Chrome 136+ does an integrity check on v10 cookies; a cloned profile silently drops `session-token` (observed 32 → 10 cookies, login lost).
2. **Why real Chrome, not bundled Chromium?** `cf_clearance` is TLS/JA3-fingerprint bound. Bundled Chromium trips Cloudflare.
3. **Why `keyboard.type()`, not `fill()`?** ChatGPT's input is a ProseMirror `contenteditable`; `fill()` doesn't fire the events that enable the send button.
4. **Why wait for the send button after upload?** Binary files (PDF/DOCX) need server-side parsing; pressing Enter too early silently does nothing (the cause of the original 120s timeouts).

## Repo layout

```
chatgpt-pro-browser/
├── skills/chatgpt-pro-browser/
│   ├── SKILL.md                       # skill metadata + instructions (loaded by ZCode)
│   ├── references/
│   │   ├── api.md                     # full harness API
│   │   ├── pitfalls.md                # 11 robustness gotchas + fixes
│   │   └── http-bridge.md             # how to wrap as an HTTP API
│   └── scripts/
│       ├── prereq_check.sh            # environment verifier
│       └── ask.py                     # one-shot CLI
├── lib/harness.py                     # the reusable driver (cookie → inject → drive)
├── fixtures/gen_fixtures.py           # 11 test-file generators
├── run_suite.py                       # test runner (single/multi/long/multi-turn)
├── examples_smoke_pdf.py              # minimal working example
├── install.sh                         # one-line installer
├── requirements.txt
└── TEST_REPORT.md                     # 20/20 test results
```

## Performance

| Task | Typical |
|---|---|
| Simple prompt | 12-25 s |
| File read (txt/json/code) | 13-20 s |
| Binary file (pdf/docx/xlsx) | 18-55 s |
| Multi-file (3-5) | 19-30 s |
| Big file locate (130 KB) | ~60 s |
| Long output (2000+ words) | ~240 s |
| Deep reasoning (GPT-5 Pro) | 20-60 s |

## Privacy & safety

- Cookies are decrypted **in-process only**, never written to disk or logged.
- The harness binds to your local machine; it does not exfiltrate credentials.
- Driving the ChatGPT web UI is against OpenAI's Terms of Service. This is a personal/research tool, same category as any browser-automation utility. Use responsibly.
- Bind any HTTP bridge to `127.0.0.1` only.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Keychain dialog denied | Re-run, click **Allow** |
| "missing auth cookies" | Log into chatgpt.com in Chrome, then retry |
| "Not on Pro plan" | Upgrade, or use `ask.py --no-pro` |
| Cloudflare challenge page | Wait 5-10 s; if persistent, re-login in Chrome |
| Empty reply / timeout | Raise `--timeout 300` for long tasks |
| Wrong context bleeds in | Call `s.new_chat()` between independent tasks |

Run `bash skills/chatgpt-pro-browser/scripts/prereq_check.sh` to diagnose environment issues.

## License

[MIT](LICENSE) — do whatever, just don't blame me if OpenAI notices.

## Acknowledgements

Built on [Playwright](https://playwright.dev). The Chrome v10 cookie decryption follows Chromium's documented macOS scheme. Inspired by the user's own `glm-pool` project structure.
