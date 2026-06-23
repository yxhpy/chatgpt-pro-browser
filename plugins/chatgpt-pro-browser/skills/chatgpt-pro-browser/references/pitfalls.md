# Pitfalls & robustness notes

These are the failure modes discovered during 20/20 test development. The harness already handles all of them — this document exists so you understand *why* and can debug if ChatGPT changes its DOM.

## 1. ProseMirror composer — `fill()` silently fails

ChatGPT's input is `div.ProseMirror[contenteditable="true"]`, not a `<textarea>`. ProseMirror listens for native `beforeinput`/`input` events. `page.fill()` and `page.locator.fill()` mutate the DOM but **do not** fire those events, so:
- the text appears visually
- but the send button stays disabled
- pressing Enter does nothing

**Fix (in harness):** `editor.click()` to focus, then `page.keyboard.type(text, delay=6)`. The `delay` mimics human typing and lets React state settle.

## 2. Send button disabled during attachment processing

After `set_input_files()`, binary files (PDF, DOCX, XLSX, images) are uploaded to OpenAI's servers and parsed. During this window (~1-5s) the send button has `aria-disabled="true"`. Pressing Enter then **silently does nothing** — the turn never starts, and `_wait_turn_done()` hits its 180s timeout returning `[NO_RESPONSE_TIMEOUT]`.

**Symptom:** PNG/DOCX tests hung at exactly 120-124s with `turns=0` throughout.

**Fix (in harness):** `upload()` calls `_wait_send_enabled(timeout=60)` which polls until the send button is found AND not disabled. `ask()` re-checks before pressing Enter.

## 3. `goto(chatgpt.com/)` resumes the last chat

Navigating to the root URL **does not** reliably start a blank chat — ChatGPT often restores the most recent conversation. This caused a CSV test to return the sentinel from a *previous* big.txt test (cross-session contamination).

**Fix (in harness):** `new_chat()` clicks `[data-testid="create-new-chat-button"]` (verified to exist) and asserts the composer is empty + zero assistant turns before returning.

## 4. Done-detection must reject placeholders

During generation, the assistant turn contains transient text that is NOT the final answer:
- `"Pro 思考中"` (Pro thinking…)
- `"已思考 Ns"` (thought for Ns)
- `"Thinking…"`
- `"Generating…"`

A naive "text stopped changing" check latches onto these and returns early.

**Fix (in harness):** `_wait_turn_done()` requires ALL of:
- the stop button (`[data-testid="stop-button"]` / aria-label Stop) is **gone**
- the send button has **reappeared**
- text is ≥2 chars
- text (lowercased) is not in the `PLACEHOLDERS` set
- text has been stable for ~0.9s (3 polls × 0.3s)

## 5. `cf_clearance` is IP + UA + TLS-fingerprint bound

The Cloudflare clearance cookie is tied to:
- the client IP
- the User-Agent
- the TLS/JA3 fingerprint (which is why **real Chrome** is required, not bundled Chromium)

Implications:
- Same Mac, same network → cookie works.
- Different network (e.g. VPN toggle) → may need re-login.
- Bundled Chromium → fails the fingerprint check, Cloudflare serves a challenge page that never resolves.

The harness pins the UA to `Chrome/149.0.0.0` (matching the installed Chrome) and uses `channel="chrome"`.

## 6. Chrome profile cloning is a trap

Naive approach: copy `~/Library/Application Support/Google/Chrome/Default` to a temp dir and `launch_persistent_context(user_data_dir=...)`.

**This loses the session.** Chrome v136+ performs an integrity check on v10 cookie values (which embed a SHA256 domain-binding prefix). When the profile is opened from a different path/context, cookies that fail the check are **silently dropped on load and not written back on close**. Observed: 32 chatgpt cookies → 10 after one open/close cycle, with `session-token` and `_puid` gone.

This is why the harness does **decryption + injection** instead of profile cloning. Do not be tempted to "optimize" by cloning the profile.

## 7. Chrome 136+ broke `--remote-debugging-port` on the default profile

The classic "launch Chrome with `--remote-debugging-port=9222` and `connectOverCDP`" trick no longer works against the default user profile (Chrome 136+ restriction). CDP attach is only allowed on a freshly-created profile. Since we need the default profile's cookies, the injection approach sidesteps this entirely.

## 8. Keychain authorization is one-time but interactive

The first `security find-generic-password -s "Chrome Safe Storage" -a Chrome` call triggers a GUI dialog. In a headless/SSH context this dialog may not appear and the call fails. If you hit this:
- Run the harness once interactively (GUI session) and click "Always Allow".
- Or pre-authorize via `security authorizationdb` (advanced; not recommended for most users).

## 9. Long outputs can exceed 180s

GPT-5 Pro with a "write 2000+ words" prompt can stream for ~4 minutes. Set `timeout=300` for known-long tasks. The harness's 0.9s stability check handles the streaming tail correctly.

## 10. Session-token expiry

`__Secure-next-auth.session-token` lasts days but not forever. When it expires, ChatGPT shows the login wall. The harness detects this in `ensure_pro()` (composer doesn't appear) and raises `RuntimeError("Login wall detected")`. Fix: open real Chrome, log into chatgpt.com once, re-run.

## 11. DOM selector drift

ChatGPT changes its DOM frequently. The harness uses the most stable selectors available:
- `div.ProseMirror[contenteditable="true"]` — the editor (ProseMirror is stable)
- `[data-testid="create-new-chat-button"]` — new chat (testids are more stable than classes)
- `[data-testid="stop-button"]`, `[data-testid="send-button"]` — generation controls
- `[data-message-author-role="assistant"]` — assistant turn (robust to turn renumbering)

Avoid hardcoded class names (e.g. `wcDTda_fallbackTextarea`) — those are hashed and change per build. If a selector breaks, check ChatGPT's current DOM in DevTools and prefer `data-testid` attributes.
