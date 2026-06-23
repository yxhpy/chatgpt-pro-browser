# chatgpt-pro-browser

> Use your **already-logged-in ChatGPT (incl. Pro)** from the terminal by driving the real Chrome browser — call it, upload files, and generate executable plans.

[![tests](https://img.shields.io/badge/tests-20%2F20%20pass-brightgreen)](TEST_REPORT.md)
[![platform](https://img.shields.io/badge/platform-macOS-lightgrey)](#prerequisites)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](requirements.txt)

This is a ZCode/Codex **plugin** (two skills) plus a reusable Python **harness** that lets you call ChatGPT (especially **GPT-5 Pro / GPT-5.5 Pro**) from scripts, automation, or other agents — by operating the actual chatgpt.com web UI with your own logged-in session.

It is **not** a reverse-engineered API. Raw HTTP/cookie access to ChatGPT is blocked by Cloudflare (`cf-mitigated: challenge`, confirmed 403). This project decrypts Chrome's login cookies and injects them into a Playwright-controlled **real** Chrome, then drives the UI like a human would.

## Two skills

| Skill | What it does |
|---|---|
| **chatgpt-pro-browser** | Call ChatGPT Pro from code: send prompts, upload files, multi-turn. The reusable `lib/harness.py`. |
| **chatgpt-pro-planner** | Generate executable engineering plans (dev / test / refactor / bugfix) via Pro's reasoning, in the **superpowers markdown format** that Codex, Claude Code, and `executing-plans` / `subagent-driven-development` consume directly. |

## What works (verified, 20/20 tests passing)

| Capability | Status |
|---|---|
| Login reuse (Pro/Plus/Free) | ✅ |
| Single prompt → text reply | ✅ |
| File uploads: PNG, JPG, PDF, CSV, TXT, JSON, PY, MD, DOCX, XLSX | ✅ |
| Multi-file uploads (3-5 files, mixed types) | ✅ |
| Cross-file reasoning | ✅ |
| Big inputs (132 KB file, 14 KB pasted prompt) | ✅ |
| Long outputs (2000+ words) | ✅ |
| Deep reasoning (GPT-5 Pro) | ✅ |
| Multi-turn conversation state | ✅ |
| **Resume after disconnect** (server keeps generating) | ✅ |
| **Multi-line/large prompts** (paste mode, no Enter-submits-early) | ✅ |

See [TEST_REPORT.md](TEST_REPORT.md) for the full matrix.

## Prerequisites

- **macOS** (uses the Keychain + Chrome's on-disk cookies).
- **Google Chrome** installed and used to log into [chatgpt.com](https://chatgpt.com) at least once.
- **Python 3.10+** with `playwright` and `cryptography`.
- A ChatGPT **Pro** subscription (for Pro models; the harness also works on Plus/Free with `--no-pro`).

## Install

### Option A: one-line (symlinks both skills into `~/.agents/skills/`)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/yxhpy/chatgpt-pro-browser/main/install.sh)
```

### Option B: clone + install

```bash
git clone https://github.com/yxhpy/chatgpt-pro-browser.git
cd chatgpt-pro-browser
bash install.sh           # or: bash install.sh --copy for a frozen snapshot
```

### Option C: as a plugin (zcode / codex)

This repo ships `.zcode-plugin/plugin.json` and `.codex-plugin/plugin.json`, so it can be added as a plugin:

```bash
# ZCode
zcode plugin marketplace add yxhpy/chatgpt-pro-browser --ref main
zcode plugin add chatgpt-pro-browser

# Codex
codex plugin marketplace add yxhpy/chatgpt-pro-browser --ref main
codex plugin add chatgpt-pro-browser
```

The first time you use it, macOS shows a Keychain dialog for **"Chrome Safe Storage"** — click **Allow** (one-time).

## Quick start

### Call ChatGPT Pro from the CLI

```bash
python3 skills/chatgpt-pro-browser/scripts/ask.py "Write a haiku about SSH keys."

# attach files
python3 skills/chatgpt-pro-browser/scripts/ask.py "Summarize this." -f report.pdf -f data.csv

# multi-line/large prompts use paste mode by default (newline-safe)
```

### Generate an executable plan via Pro

```bash
# dev plan (TDD tasks, ready for executing-plans / subagent-driven-development)
python3 skills/chatgpt-pro-planner/scripts/plan.py dev "Add streaming to the harness" --context lib/harness.py

# test / refactor / bugfix plans
python3 skills/chatgpt-pro-planner/scripts/plan.py test "Cover the cookie path" --context lib/harness.py
python3 skills/chatgpt-pro-planner/scripts/plan.py refactor "Extract cookie logic into cookies.py"
python3 skills/chatgpt-pro-planner/scripts/plan.py bugfix "Upload hangs when send stays disabled" --context lib/harness.py
```

Plans are saved to `docs/superpowers/plans/YYYY-MM-DD-<feature>-<type>.md` and validated with:

```bash
python3 skills/chatgpt-pro-planner/scripts/validate_plan.py <plan.md>
```

### From Python

```python
import asyncio
from lib.harness import ChatGPTSession

async def main():
    async with ChatGPTSession(headless=False) as s:
        await s.ensure_pro()
        r = await s.ask("What model are you?")
        print(r.text)            # the reply
        print(r.completed)       # True if finished in-session
        print(r.chat_url)        # https://chatgpt.com/c/<id> — for resume

        # upload + ask
        r = await s.ask("Summarize this PDF.", attachments=["report.pdf"])

        # multi-turn (same session keeps context)
        await s.ask("Now translate that to Chinese.")

asyncio.run(main())
```

### Resume after a long task (resume-safe)

ChatGPT keeps generating **server-side** after the browser disconnects (verified: a 300-word reply that was empty in-session came back complete at 2097 chars after a reconnect). So a timed-out `ask()` is never lost:

```python
r = await s.ask("Write a 2000-word essay...", timeout=120)
if not r.completed:
    # server is still generating — reconnect and read the full reply
    r = await s.resume(r.chat_url, timeout=300)
print(r.text)
```

`resume()` works even in a **fresh** `ChatGPTSession` — the chat is identified by URL, not browser state.

## How it works

```
            macOS Keychain
       ┌──────────────────────┐
       │ "Chrome Safe Storage" │── PBKDF2-SHA1(saltysalt, 1003) ──► AES-128 key
       └──────────┬───────────┘
                  │
   ~/.../Chrome/  │
   Default/       ▼
   Cookies.sqlite ──► decrypt v10 cookie blobs → session-token, _puid, cf_clearance…
                  │
                  ▼
        Playwright ── channel="chrome"  (REAL Chrome — Cloudflare-safe)
        new_context ── ctx.add_cookies([...])
                  │
                  ▼
        page.goto("chatgpt.com/")  ── logged in (Pro), no CF challenge
                  │
                  ▼
        div.ProseMirror → execCommand insertText (paste mode, newline-safe)
                       → click send button → poll until stop-button vanishes
                  │
                  ▼
        read assistant reply  (or resume(chat_url) later if it timed out)
```

Key technical points (full detail in [skills/chatgpt-pro-browser/references/pitfalls.md](skills/chatgpt-pro-browser/references/pitfalls.md)):

1. **Decrypt + inject, don't clone the profile** — Chrome 136+ integrity-checks v10 cookies; a cloned profile silently drops `session-token`.
2. **Real Chrome, not bundled Chromium** — `cf_clearance` is TLS/JA3-fingerprint bound.
3. **Paste mode for input** — `execCommand('insertText')` handles multi-line/large prompts without Enter submitting early. (`keyboard.type()` is the legacy fallback.)
4. **Send-button click to submit** — immune to multi-line content; waits for the button to re-enable after uploads (binary files need server-side parse).
5. **Resume-safe** — `ask()` captures the `/c/<id>` URL; on timeout, `resume()` reopens it. Server generation is independent of the browser.

## Repo layout

```
chatgpt-pro-browser/
├── .zcode-plugin/plugin.json          # ZCode plugin manifest
├── .codex-plugin/plugin.json          # Codex plugin manifest
├── skills/
│   ├── chatgpt-pro-browser/           # call ChatGPT Pro
│   │   ├── SKILL.md
│   │   ├── references/ (api.md, pitfalls.md, http-bridge.md)
│   │   └── scripts/ (ask.py, prereq_check.sh)
│   └── chatgpt-pro-planner/           # generate executable plans via Pro
│       ├── SKILL.md
│       ├── references/ (output-contract.md, {dev,test,refactor,bugfix}-template.md)
│       └── scripts/ (plan.py, validate_plan.py)
├── lib/harness.py                     # reusable driver (decrypt → inject → drive → resume)
├── fixtures/ + run_suite.py           # 20/20 test suite
├── install.sh                         # one-line installer (both skills)
└── TEST_REPORT.md
```

## Performance

| Task | Typical |
|---|---|
| Simple prompt | 12-25 s |
| File read (txt/json/code) | 13-20 s |
| Binary file (pdf/docx/xlsx) | 18-55 s |
| Plan generation (single round) | 60-180 s |
| Long output (2000+ words) | ~240 s |
| Deep reasoning (GPT-5 Pro) | 30-120 s |

Long tasks may exceed a single `ask()` budget — that's exactly what `resume()` is for.

## Privacy & safety

- Cookies are decrypted **in-process only**, never written to disk or logged.
- The harness binds to your local machine; it does not exfiltrate credentials.
- Driving the ChatGPT web UI is against OpenAI's Terms of Service. Personal/research use.
- Bind any HTTP bridge to `127.0.0.1` only.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Keychain dialog denied | Re-run, click **Allow** |
| "missing auth cookies" | Log into chatgpt.com in Chrome, retry |
| "Login wall detected" | Reload failed too — re-login in Chrome |
| Cloudflare challenge page | Wait 5-10 s; if persistent, re-login |
| Empty reply / `completed=False` | Call `resume(chat_url)` — server still generating |
| Wrong context bleeds in | Call `s.new_chat()` between independent tasks |

Run `bash skills/chatgpt-pro-browser/scripts/prereq_check.sh` to diagnose environment issues.

## License

[MIT](LICENSE)
