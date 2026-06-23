# API reference — `lib/harness.py`

## `ChatGPTSession`

Async context manager that drives one logged-in ChatGPT Pro session.

### Constructor

```python
ChatGPTSession(headless: bool = False, viewport: tuple[int,int] = (1280, 800))
```

- `headless=False` — recommended. A visible window passes Cloudflare more reliably.
- `viewport` — browser window size.

### Lifecycle

```python
async with ChatGPTSession(headless=False) as s:
    await s.ensure_pro()
    ...
# browser closes on exit
```

On `__aenter__` the session:
1. Decrypts Chrome cookies via the macOS Keychain.
2. Verifies the critical auth cookies (`__Secure-next-auth.session-token.0`, `_puid`) are present — raises `RuntimeError` if the user isn't logged in.
3. Launches real Chrome (`channel="chrome"`) with a fresh context.
4. Injects cookies via `ctx.add_cookies([...])`.
5. Navigates to `https://chatgpt.com/` and waits for network idle.

### Methods

#### `await ensure_pro() -> None`
Calls `current_plan()` and raises `RuntimeError` if the plan isn't `"pro"`. Also waits for the composer to appear (detects login-wall vs. real session). Call once at startup.

#### `await current_plan() -> str`
Returns the `chatgpt_plan_type` claim from the session JWT: `"pro"`, `"plus"`, `"free"`, `"HTTP_403"` (Cloudflare block), `"NO_TOKEN"` (logged out), or `"UNKNOWN"`.

#### `await ask(prompt, attachments=None, type_delay=6, timeout=180) -> TurnResult`
The main entry point. Focuses the composer, optionally uploads attachments, types the prompt, presses Enter, and waits for completion.

- `prompt: str` — the text to send. Multi-line is fine; use `\n`.
- `attachments: list[str] | None` — paths to files to attach. Supports PDF, DOCX, XLSX, PPTX, CSV, JSON, TXT, MD, PY, PNG, JPG, and more.
- `type_delay: int` — milliseconds between keystrokes (mimics human typing; default 6).
- `timeout: float` — max seconds to wait for the response (default 180; raise to 300 for deep-reasoning/long-output).

Returns `TurnResult(text, plan, elapsed, error, raw_metadata)`.

#### `await upload(*paths, ready_timeout=60) -> None`
Attach files without submitting. Blocks until the send button re-enables (binary files need server-side parsing). Usually you don't call this directly — `ask(attachments=...)` does it for you.

#### `await new_chat() -> None`
Start a fresh isolated chat. **Call between independent tasks.** Clicks `[data-testid="create-new-chat-button"]` and verifies the composer is empty. Do not assume `goto(chatgpt.com/)` starts fresh — it resumes the last chat (cross-talk bug).

### `TurnResult`

| field | type | notes |
|---|---|---|
| `text` | `str` | the assistant's final reply |
| `plan` | `str` | plan at the time of the call |
| `elapsed` | `float` | wall-clock seconds |
| `error` | `str \| None` | set if something went wrong |
| `raw_metadata` | `dict` | reserved |

## Cookie functions (advanced)

```python
from harness import load_chatgpt_cookies
cookies = load_chatgpt_cookies()  # list[dict] in Playwright format
```

Returns Playwright-format cookies for `chatgpt.com` + `openai.com`. Use this if you want to inject into your own Playwright context instead of `ChatGPTSession`.

## Constants

- `PROFILE` — `~/Library/Application Support/Google/Chrome`
- `COOKIES_DB` — `<PROFILE>/Default/Cookies`
- `UA` — the User-Agent string used (Chrome 149 on macOS)

## Error handling

| Exception | Meaning | Fix |
|---|---|---|
| `PermissionError("Keychain denied")` | user denied the Keychain prompt | re-run, click Allow |
| `RuntimeError("missing auth cookies")` | not logged into ChatGPT in Chrome | log in at chatgpt.com in Chrome |
| `RuntimeError("Not on Pro plan")` | logged in but not Pro | upgrade, or remove `ensure_pro()` for Plus/Free |
| `RuntimeError("Login wall detected")` | session-token expired | re-login in Chrome |
| `RuntimeError("No file <input>")` | composer not loaded | check network; retry |
