---
name: chatgpt-pro-browser
description: Use the user's already-logged-in ChatGPT (incl. Pro/Plus) directly from the terminal by driving the real Chrome browser — bypassing the broken API-key/HTTP-cookie paths. Use whenever the user wants to call ChatGPT (especially Pro models like GPT-5 Pro / GPT-5.5 Pro) from scripts, automation, or another agent, send prompts to ChatGPT, upload files to ChatGPT, do multi-turn conversations with ChatGPT, or anything where they say "用我的 ChatGPT", "调用 ChatGPT Pro", "用浏览器调 chatgpt", "复用我登录的 chatgpt", "drive chatgpt", "ask chatgpt pro", or reference GPT-5/5.5 Pro. macOS only.
---

# ChatGPT Pro Browser

Drive the user's **real, already-logged-in** ChatGPT session (incl. Pro) from code by decrypting Chrome's login cookies and injecting them into a Playwright-controlled real Chrome. This is **not** a reverse-engineered API — it operates the actual chatgpt.com web UI, so it works even though Cloudflare blocks raw HTTP clients (a confirmed 403 on the session endpoint).

## When to use this skill

Use it whenever the user wants to programmatically call ChatGPT from their own machine, especially:
- "用我登录的 ChatGPT" / "用我的 Pro" / "调用 chatgpt pro"
- Send a prompt to ChatGPT and get the reply as a string
- Upload files (PDF/DOCX/XLSX/images/code/etc.) and have ChatGPT read them
- Multi-turn conversations with state retention
- Long/deep tasks (GPT-5 Pro reasoning, big inputs, long outputs)
- Bridging ChatGPT into another tool or agent that only speaks HTTP

Do **not** use this for:
- The official OpenAI API (`platform.openai.com`) — that's a normal API key, no browser needed.
- Non-macOS machines — this skill relies on the macOS Keychain + Chrome.

## How it works (one paragraph)

Chrome stores ChatGPT's login cookies (`__Secure-next-auth.session-token`, `_puid`, `cf_clearance`, …) AES-encrypted (v10 scheme) in `~/Library/Application Support/Google/Chrome/Default/Cookies`. The AES key is derived from the "Chrome Safe Storage" secret in the macOS Keychain. We decrypt those cookies, inject them into a fresh Playwright context launched with `channel="chrome"` (the **real** Google Chrome binary — critical for Cloudflare's `cf_clearance` TLS-fingerprint check), then drive the ProseMirror composer via real keyboard events. Verified end-to-end: logs in as Pro, submits prompts, gets GPT-5.5 Pro responses.

## Prerequisites

Read and run the bundled `scripts/prereq_check.sh` first — it verifies:
1. macOS (uses Keychain + Chrome paths)
2. Google Chrome installed at `/Applications/Google Chrome.app`
3. The user has logged into chatgpt.com in Chrome **at least once** (so the cookies exist)
4. Python 3.10+ with `playwright`, `cryptography` installed
5. Playwright's Chromium browser downloaded (`python -m playwright install chromium`)

```bash
bash skills/chatgpt-pro-browser/scripts/prereq_check.sh
```

The first time this skill reads cookies, macOS will pop a Keychain authorization dialog for "Chrome Safe Storage". The user must click **Allow** (or Always Allow). This is one-time.

## The core driver: `lib/harness.py`

This is the reusable module. Import `ChatGPTSession` and call `.ask()`.

```python
import asyncio, sys
# The harness lives at <repo>/lib/harness.py — add it to the path
sys.path.insert(0, "<repo>/lib")
from harness import ChatGPTSession

async def main():
    async with ChatGPTSession(headless=False) as s:
        await s.ensure_pro()          # raises if not logged in / not Pro
        r = await s.ask("Write a haiku about SSH keys.")
        print(r.text)                 # the assistant's reply (string)
        print(r.elapsed)              # seconds

        # upload files:
        r = await s.ask(
            "Summarize this PDF.",
            attachments=["/path/to/doc.pdf"],
        )

        # multi-turn (same session keeps context):
        r2 = await s.ask("Now translate that to Chinese.")

asyncio.run(main())
```

`headless=False` is recommended — some Cloudflare challenges need a visible window. For unattended runs, `headless=True` works once the session is warm but may occasionally trip a challenge.

## API reference (full detail in `references/api.md`)

- `ChatGPTSession(headless=False, viewport=(1280,800))` — async context manager.
- `await s.ensure_pro()` — verifies plan is "pro"; raises `RuntimeError` if not logged in or on a lower tier. Call once at startup.
- `await s.current_plan()` — returns the plan string (`"pro"`, `"plus"`, `"free"`, or `"NO_TOKEN"`).
- `await s.ask(prompt, attachments=None, type_delay=6, timeout=180)` → `TurnResult(text, plan, elapsed)`.
- `await s.upload(*paths)` — attach files without submitting.
- `await s.new_chat()` — start a fresh isolated chat. **Always call this between independent tasks** — `chatgpt.com/` resumes the last chat otherwise (cross-talk bug, see `references/pitfalls.md`).

## Important behaviors (learned the hard way — read `references/pitfalls.md`)

1. **ProseMirror, not textarea.** ChatGPT's input is `div.ProseMirror[contenteditable]`. `page.fill()` does NOT work — use `keyboard.type()` (the harness already does).
2. **Wait for the send button to re-enable after uploads.** Binary files (PDF/DOCX/images) take server-side parse time; pressing Enter too early silently does nothing (looks like a 120s hang). The harness's `upload()` blocks until ready.
3. **New chat via button, not URL.** Navigating to `chatgpt.com/` often resumes the previous conversation. Use `new_chat()` which clicks `[data-testid="create-new-chat-button"]`.
4. **Done-detection.** Don't trust text-stability alone — "Pro 思考中" / "Thinking…" placeholders appear during generation. The harness waits for the **stop button to disappear + send to reappear + 0.9s stability**.
5. **`cf_clearance` is IP+UA-bound.** Works on the same Mac/network. If the user changes network, they may need to re-login in Chrome.

## Performance expectations

| Task | Typical time |
|---|---|
| Simple prompt | 12-25s |
| File read (txt/json/code) | 13-20s |
| Binary file (pdf/docx/xlsx) | 18-55s |
| Multi-file (3-5 files) | 19-30s |
| Big file locate (130KB) | ~60s |
| Long output (2000+ words) | ~240s |
| Deep reasoning (GPT-5 Pro) | 20-60s |

## Wrapping as an HTTP API (optional)

If the user wants an OpenAI-compatible endpoint, wrap the harness in FastAPI. The existing `glm-pool` project (`~/ZCodeProject/glm-pool/server.py`) is a good template — single-file, binds 127.0.0.1, maps `/v1/chat/completions`. Point the bridge at this harness's `ask()`. Details in `references/http-bridge.md`.

## Testing

The repo ships a full test suite (20/20 passing). Run it to verify the install works on this machine:

```bash
cd <repo>
python run_suite.py --only single        # 10 file types
python run_suite.py --only multi,long,multi-turn
```

Results land in `results/*.jsonl`. See `TEST_REPORT.md` for the reference run.

## Privacy & safety

- Cookies are decrypted **in-process only** and never written to disk or logged.
- The skill binds to the local machine; it does not exfiltrate credentials.
- This drives the ChatGPT web UI, which is against OpenAI's ToS for automated access. Use for personal/research purposes only, same as any browser-automation tool.
