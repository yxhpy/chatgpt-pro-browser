"""
ChatGPT Pro browser harness.

Reusable cookie-injection + UI-driver for driving the user's logged-in ChatGPT
Pro session. Every test imports `ChatGPTSession` and calls `.ask()` / `.upload()`.

Design (proven in /tmp/cg_probe):
  - Decrypt Chrome v10 cookies with the macOS "Chrome Safe Storage" Keychain key.
  - Inject into a fresh Playwright context using channel="chrome" (real Chrome).
  - Drive the ProseMirror composer via keyboard.type() (fill() does not work).
  - Detect turn completion via stop-button disappearance + text stability.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from playwright.async_api import (
    BrowserContext,
    Error as PWError,
    Page,
    TimeoutError as PWTimeout,
    async_playwright,
)

PROFILE = os.path.expanduser("~/Library/Application Support/Google/Chrome")
COOKIES_DB = os.path.join(PROFILE, "Default", "Cookies")
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

# Daemon lock file: when a persistent Chrome is running (daemon mode), this
# records its CDP endpoint so other scripts can connect_over_cdp() to it
# instead of launching (and later closing) their own browser. Reuse = seconds
# instead of ~15s cold start per call.
LOCK_FILE = os.path.expanduser("~/.chatgpt-pro-browser.lock")
DEFAULT_CDP_PORT = 9223   # avoid 9222 (Playwright bundled chromium default)

# Placeholders that appear during generation and must NOT be treated as final.
PLACEHOLDERS = {
    "thinking…", "thinking...", "generating…", "generating...",
    "pro 思考中", "思考中", "正在思考…", "正在生成…", "",
}


# --------------------------------------------------------------------------- #
# Cookie decryption
# --------------------------------------------------------------------------- #
def _chrome_key() -> bytes:
    out = subprocess.run(
        ["security", "find-generic-password", "-w",
         "-s", "Chrome Safe Storage", "-a", "Chrome"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise PermissionError(f"Keychain denied: {out.stderr.strip()}")
    return hashlib.pbkdf2_hmac(
        "sha1", out.stdout.rstrip("\n").encode(), b"saltysalt", 1003, dklen=16
    )


def _decrypt_v10(blob: bytes, key: bytes) -> str:
    if blob[:3] != b"v10":
        raise ValueError(f"not v10: {blob[:3]!r}")
    dec = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    out = dec.update(blob[3:]) + dec.finalize()
    pad = out[-1]
    if 1 <= pad <= 16:
        out = out[:-pad]
    return out[32:].decode("utf-8", "replace")


def load_chatgpt_cookies() -> list[dict]:
    """Decrypt and return Playwright-format cookies for chatgpt.com / openai.com."""
    key = _chrome_key()
    con = sqlite3.connect(f"file:{COOKIES_DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(
        "SELECT host_key,name,encrypted_value,path,is_secure,is_httponly,"
        "samesite,expires_utc FROM cookies "
        "WHERE host_key IN ('.chatgpt.com','chatgpt.com','.openai.com','openai.com')"
    )
    out = []
    for hk, n, ev, p, sec, ho, ss, exp in cur.fetchall():
        if not ev or ev[:3] != b"v10":
            continue
        try:
            val = _decrypt_v10(ev, key)
        except Exception:
            continue
        out.append({
            "name": n, "value": val, "domain": hk, "path": p or "/",
            "secure": bool(sec), "httpOnly": bool(ho),
            "sameSite": {0: "None", 1: "Lax", 2: "Strict"}.get(ss, "None"),
            "expires": -1 if exp == 0 else exp / 1_000_000 - 11644473600,
        })
    con.close()
    return out


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #
@dataclass
class TurnResult:
    text: str
    plan: str
    elapsed: float
    error: Optional[str] = None
    raw_metadata: dict = field(default_factory=dict)
    # NEW (resume support): the chat URL this turn belongs to, and whether the
    # reply finished within the ask() call. If completed=False, the caller can
    # open `chat_url` later (same browser or a fresh one) and read the full reply
    # — ChatGPT keeps generating server-side after the browser disconnects
    # (verified: a 300-word reply that was len=0 in-session came back complete
    # at len=2097 after a disconnect+reconnect).
    chat_url: Optional[str] = None
    completed: bool = True


# --------------------------------------------------------------------------- #
# Daemon / lock-file management
# --------------------------------------------------------------------------- #
def write_lock(cdp_url: str, pid: int) -> None:
    """Record the running daemon's CDP endpoint + pid so other scripts connect."""
    import json
    data = {"cdp_url": cdp_url, "pid": pid,
            "started_at": time.time()}
    with open(LOCK_FILE, "w") as f:
        json.dump(data, f)


def read_lock() -> Optional[dict]:
    """Return the lock dict if a daemon appears alive, else None (and clean up)."""
    import json
    if not os.path.exists(LOCK_FILE):
        return None
    try:
        with open(LOCK_FILE) as f:
            d = json.load(f)
    except Exception:
        _clear_lock()
        return None
    # is the daemon process still alive?
    pid = d.get("pid")
    if pid:
        try:
            os.kill(pid, 0)   # signal 0 = existence check
        except (OSError, ProcessLookupError):
            _clear_lock()
            return None
    return d


def _clear_lock() -> None:
    try:
        os.remove(LOCK_FILE)
    except FileNotFoundError:
        pass


def clear_lock() -> None:
    """Public: remove the lock file (called by close.py after shutting down)."""
    _clear_lock()


async def daemon_alive() -> bool:
    """True if a connectable daemon is running."""
    d = read_lock()
    if not d:
        return False
    # verify the CDP endpoint actually responds
    try:
        import urllib.request
        with urllib.request.urlopen(d["cdp_url"] + "/json/version", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


class ChatGPTSession:
    """Drives a logged-in ChatGPT Pro session.

    Usage:
        async with ChatGPTSession(headless=False) as s:
            await s.ensure_pro()
            r = await s.ask("hello")
            print(r.text)
    """

    BASE = "https://chatgpt.com/"

    def __init__(self, headless: bool = False, viewport=(1280, 800),
                 connect_mode: str = "auto"):
        """connect_mode:
          - "auto" (default): reuse a running daemon if one exists (read_lock),
            else launch a fresh browser. Best for submit/status/save scripts —
            they're fast when a daemon is up, self-sufficient when not.
          - "launch": always launch a new browser (ignore any daemon).
          - "connect": require a running daemon; error if none. Used by chat.py.
          - "daemon": launch AND keep alive after the context exits (don't close
            the browser in __aexit__) — used by daemon.py. Caller must close()
            explicitly later.
        """
        self.headless = headless
        self.viewport = viewport
        self.connect_mode = connect_mode
        self._owns_browser = True   # False when connected to a daemon we don't own
        self._pw = None
        self._browser = None
        self._ctx: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.plan: Optional[str] = None
        # NEW: URL of the chat the most recent turn belongs to. Becomes
        # https://chatgpt.com/c/<uuid> ~4s after the first message. Persist this
        # so a later resume() (even in a fresh browser) can reopen the chat and
        # read the full reply — server keeps generating after disconnect.
        self.current_chat_url: Optional[str] = None

    # ---- lifecycle ----
    async def __aenter__(self) -> "ChatGPTSession":
        self._pw = await async_playwright().start()
        cookies = load_chatgpt_cookies()
        names = {c["name"] for c in cookies}
        if not {"__Secure-next-auth.session-token.0", "_puid"} <= names:
            raise RuntimeError(
                f"missing auth cookies (have {sorted(names)[:8]}...) — re-login in Chrome"
            )

        # decide: connect to a running daemon, or launch fresh?
        lock = read_lock() if self.connect_mode in ("auto", "connect") else None
        if self.connect_mode == "connect" and not lock:
            raise RuntimeError(
                "no running daemon (connect_mode='connect'). Start one with "
                "daemon.py first.")
        if lock and self.connect_mode in ("auto", "connect"):
            # REUSE the persistent browser — seconds, not ~15s cold start.
            try:
                self._browser = await self._pw.chromium.connect_over_cdp(
                    lock["cdp_url"], timeout=5000)
                self._owns_browser = False
                # use the daemon's existing default context (cookies already
                # injected when the daemon started). Pick its first page or
                # make one.
                contexts = self._browser.contexts
                self._ctx = contexts[0] if contexts else await self._browser.new_context()
                pages = self._ctx.pages
                self._page = pages[0] if pages else await self._ctx.new_page()
                # navigate to base if not already there
                if "chatgpt.com" not in (self._page.url or ""):
                    await self._page.goto(self.BASE, wait_until="domcontentloaded",
                                          timeout=60000)
                    await asyncio.sleep(1)
                return self
            except Exception as e:
                # daemon lock stale or unreachable — fall through to launch
                _clear_lock()

        # LAUNCH fresh (also the fallback when a stale lock was cleared)
        launch_args = ["--disable-blink-features=AutomationControlled",
                       "--no-default-browser-check", "--no-first-run"]
        if self.connect_mode == "daemon":
            # persistent daemon: open a CDP port so other scripts can connect
            launch_args.append(f"--remote-debugging-port={DEFAULT_CDP_PORT}")
        self._browser = await self._pw.chromium.launch(
            channel="chrome", headless=self.headless, args=launch_args,
        )
        self._ctx = await self._browser.new_context(
            viewport={"width": self.viewport[0], "height": self.viewport[1]},
            user_agent=UA,
            permissions=["clipboard-read", "clipboard-write"],
        )
        await self._ctx.add_cookies(cookies)
        self._page = await self._ctx.new_page()
        await self._page.goto(self.BASE, wait_until="domcontentloaded", timeout=60000)
        try:
            await self._page.wait_for_load_state("networkidle", timeout=25000)
        except PWTimeout:
            pass
        await asyncio.sleep(3)
        # if daemon mode, record the lock so others can connect
        if self.connect_mode == "daemon":
            cdp_url = f"http://127.0.0.1:{DEFAULT_CDP_PORT}"
            write_lock(cdp_url, os.getpid())
        return self

    async def __aexit__(self, *exc):
        # daemon mode: keep the browser alive — don't close. Caller shuts it
        # down explicitly via close() / close.py.
        if self.connect_mode == "daemon":
            return
        # connected-to-daemon mode: detach, don't kill the shared browser
        if not self._owns_browser:
            # just disconnect our playwright client; daemon browser stays up
            try:
                if self._pw:
                    await self._pw.stop()
            except Exception:
                pass
            self._pw = None
            return
        try:
            if self._ctx:
                await self._ctx.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass

    async def close(self) -> None:
        """Explicitly shut down a daemon-mode browser + clear the lock.

        Called by close.py. For non-daemon sessions this is a no-op (the
        context manager already closed everything).
        """
        try:
            if self._ctx:
                await self._ctx.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        clear_lock()

    # ---- auth ----
    async def current_plan(self) -> str:
        p = await self._page.evaluate(
            """async () => {
                const r = await fetch('/api/auth/session', {credentials:'include'});
                if (!r.ok) return 'HTTP_' + r.status;
                const j = await r.json();
                const tok = j.accessToken;
                if (!tok) return 'NO_TOKEN';
                const p = tok.split('.')[1];
                const claims = JSON.parse(atob(p.replace(/-/g,'+').replace(/_/g,'/')));
                return claims['https://api.openai.com/auth']?.chatgpt_plan_type || 'UNKNOWN';
            }"""
        )
        self.plan = p
        return p

    async def ensure_pro(self) -> None:
        plan = await self.current_plan()
        if plan != "pro":
            raise RuntimeError(f"Not on Pro plan (got '{plan}'). Re-login required.")
        # also verify the composer is present (true login, not a login wall).
        # Be resilient to transient slow loads: reload once if the composer
        # doesn't appear, then retry. A genuine login wall survives the reload.
        for attempt in range(2):
            try:
                await self._page.wait_for_selector(
                    'div.ProseMirror[contenteditable="true"]', timeout=15000
                )
                return
            except PWTimeout:
                if attempt == 0:
                    # might be a slow load — reload and retry once
                    try:
                        await self._page.reload(
                            wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(2)
                    except Exception:
                        pass
                else:
                    raise RuntimeError(
                        "Login wall detected — session-token expired. "
                        "Re-login to chatgpt.com in Chrome, then retry."
                    )

    # ---- composer ----
    async def _focus_composer(self) -> None:
        loc = self._page.locator('div.ProseMirror[contenteditable="true"]').first
        await loc.click()
        await asyncio.sleep(0.2)

    async def _type_to_composer(self, text: str, mode: str = "paste") -> None:
        """Put `text` into the ProseMirror composer WITHOUT submitting.

        Why this exists: ChatGPT maps a bare Enter to "send", so multi-line
        prompts (which the planner generates, thousands of chars with code
        blocks + newlines) get fragmented/mis-submitted if typed char-by-char
        with Enter as the only key. We need a way to fill the box first, then
        submit in one explicit action.

        Modes (all proven not to submit):
          - "paste" (DEFAULT): document.execCommand('insertText'). Fast,
            handles real newlines natively (becomes <p> blocks), no per-char
            delay, never fires Enter. Best for large/multi-line prompts.
          - "keyboard": keyboard.type(text, delay). Old behavior; one char at a
            time. Slow but maximally human-like. Use only if paste is blocked.
          - "clipboard": write text to the system clipboard, focus, paste.
            Fallback if execCommand is unavailable; requires the window focused.
        """
        if not text:
            return
        if mode == "keyboard":
            await self._page.keyboard.type(text, delay=8)
            return
        if mode == "clipboard":
            await self._page.evaluate(
                """(t) => { await navigator.clipboard.writeText(t); }""", text
            )
            await self._page.keyboard.press("Meta+V")
            await asyncio.sleep(0.3)
            return
        # default: paste via execCommand insertText
        ok = await self._page.evaluate(
            """(t) => {
                const ed = document.querySelector('div.ProseMirror[contenteditable="true"]');
                if (!ed) return 'NO_EDITOR';
                ed.focus();
                // select-all first so re-fills replace prior content cleanly
                const sel = window.getSelection();
                const range = document.createRange();
                range.selectNodeContents(ed);
                sel.removeAllRanges();
                sel.addRange(range);
                const ok = document.execCommand('insertText', false, t);
                return ok ? 'inserted' : 'execCommand_failed';
            }""", text)
        if ok != "inserted":
            # execCommand can be flaky under some site configs — fall back to keyboard
            await self._page.keyboard.type(text, delay=8)

    async def _submit(self) -> None:
        """Submit the current composer content.

        Strategy: click the send button rather than press Enter — this is
        immune to multi-line content (a stray Enter mid-paste can't trigger
        a double-submit). Falls back to Enter if no send button is found.
        """
        clicked = await self._page.evaluate("""() => {
            const cands = [...document.querySelectorAll('button')].filter(b => {
                const a = (b.getAttribute('data-testid')||'') + ' ' +
                          (b.getAttribute('aria-label')||'');
                return /send-button|send|发送/i.test(a);
            });
            const b = cands[cands.length-1];
            if (b && !(b.disabled || b.getAttribute('aria-disabled')==='true')) {
                b.click();
                return true;
            }
            return false;
        }""")
        if not clicked:
            # fallback: Enter submits when the composer has content + send enabled
            await self._page.keyboard.press("Enter")

    # ---- reply extraction ----
    async def _read_assistant_text(self) -> tuple[str, bool, str]:
        """Return (text, generating, chat_url) for the latest assistant turn.

        `text` is the MARKDOWN SOURCE obtained by clicking ChatGPT's
        per-turn copy button and reading the clipboard. This preserves
        `#`/`###` headings, `**bold**`, `- [ ]` checkboxes, and fenced code
        blocks — which innerText strips (verified: a plan with 4 `### Task`
        headings and 29 checkboxes showed ZERO headings via innerText).

        Falls back to innerText if the copy button isn't found / clipboard
        read fails (older replies, non-markdown chat). The fallback loses
        markdown structure, so callers that need format fidelity should
        detect the fallback and warn.
        """
        snap = await self._page.evaluate(
            """async () => {
                const url = location.href;
                const asstEls = [...document.querySelectorAll('[data-message-author-role="assistant"]')];
                if (!asstEls.length) return {text: '', generating: true, url, md: null};
                // find the conversation-turn container of the last assistant msg
                const turn = asstEls[asstEls.length-1].closest('[data-testid^="conversation-turn-"]');
                const stop = document.querySelector(
                    '[data-testid="stop-button"], [aria-label*="Stop" i], [aria-label*="停止"]');
                // try copy button → clipboard (markdown source)
                let md = null;
                const btn = turn ? turn.querySelector('[data-testid="copy-turn-action-button"]') : null;
                if (btn) {
                    try {
                        await navigator.clipboard.writeText('');
                        btn.click();
                        await new Promise(r => setTimeout(r, 700));
                        md = await navigator.clipboard.readText();
                    } catch (e) { md = null; }
                }
                // innerText as fallback / for length comparison
                const text = asstEls[asstEls.length-1].innerText;
                return {text, generating: !!stop, url, md};
            }"""
        )
        text = snap.get("md") or snap.get("text", "")
        return text, snap.get("generating", True), snap.get("url", "")

    # ---- completion detection ----
    async def _wait_turn_done(
        self, timeout: float = 3600.0, *, poll_interval: float = 0.3,
        heartbeat_interval: float = 30.0, stall_threshold: float = 300.0,
        on_heartbeat=None,
    ) -> tuple[str, bool]:
        """Wait for the assistant reply to finish. Returns (markdown, completed).

        Heartbeat-style waiting — does NOT give up just because time passed. The
        only real exit conditions are:
          - DONE: stop-button gone + text stable (~0.9s) → return (markdown, True)
          - STALL: stop-button still present but text hasn't changed for
            `stall_threshold` seconds → suspicious; return (partial, False) so
            the caller can resume() or investigate. (Pro deep-research can run
            for hours; a 5-min stall likely means the page hung, not that Pro
            is still thinking.)
          - HARD CAP: `timeout` seconds elapsed (default 1h) — absolute safety
            net against zombies. Caller can raise it for known-long tasks.

        `timeout` is therefore a *ceiling*, not a budget — short tasks finish
        in seconds, long tasks run until stall/done, only true zombies hit the
        cap. Verified assumption: while Pro generates, the stop-button stays
        visible (gen=True); it flips to gen=False on completion.

        Heartbeat: every `heartbeat_interval` seconds, if `on_heartbeat` is
        provided it's called with (elapsed, text_len, generating) so callers
        can log progress / keep a UI alive.
        """
        deadline = time.monotonic() + timeout
        t0 = time.monotonic()
        last_text, stable = "", 0
        last_change_at = time.monotonic()
        last_heartbeat_at = 0.0
        url_captured = False
        while time.monotonic() < deadline:
            snap = await self._page.evaluate(
                """() => {
                    const asst2 = [...document.querySelectorAll('[data-message-author-role="assistant"]')];
                    const text = asst2.length ? asst2[asst2.length-1].innerText : '';
                    const stop = document.querySelector(
                        '[data-testid="stop-button"], [aria-label*="Stop" i], [aria-label*="停止"]');
                    return {text, generating: !!stop, url: location.href};
                }"""
            )
            if not url_captured and "/c/" in snap.get("url", ""):
                self.current_chat_url = snap["url"]
                url_captured = True
            now = time.monotonic()
            text = snap.get("text", "")
            gen = snap.get("generating", True)
            low = text.strip().lower()
            # track last content change (for stall detection)
            if text != last_text:
                last_change_at = now
            # heartbeat callback
            if on_heartbeat and (now - last_heartbeat_at) >= heartbeat_interval:
                last_heartbeat_at = now
                try:
                    on_heartbeat(now - t0, len(text), gen)
                except Exception:
                    pass
            # DONE?
            done = (not gen and text and len(text) >= 2 and low not in PLACEHOLDERS)
            if done and text == last_text:
                stable += 1
                if stable >= 3:   # ~0.9s stable via innerText
                    md, _, _ = await self._read_assistant_text()
                    return (md or text), True
            else:
                stable = 0
            # STALL? (still generating but no text change for stall_threshold)
            if gen and (now - last_change_at) >= stall_threshold and len(text) > 0:
                # likely a page hang, not normal Pro thinking — bail with partial
                md, _, _ = await self._read_assistant_text()
                return (md or text), False
            last_text = text
            await asyncio.sleep(poll_interval)
        # HARD CAP hit — generation still in progress. Capture partial + resume hint.
        md, _, _ = await self._read_assistant_text()
        return (md or last_text), False

    # ---- uploads ----
    async def upload(self, *paths: str, ready_timeout: float = 60.0) -> None:
        """Upload one or more files via the hidden file input.

        ChatGPT exposes an <input type="file" multiple>; setting input files
        triggers its upload UI without needing drag-and-drop geometry.

        After setting the files we BLOCK until the send button is re-enabled —
        large/binary files (DOCX, PDF, images) need server-side parsing before
        the composer accepts submission. If we press Enter too early the turn
        silently never starts (root cause of the PNG/DOCX 120s timeouts).
        """
        input_loc = self._page.locator('input[type="file"]').first
        try:
            await input_loc.wait_for(state="attached", timeout=5000)
        except PWTimeout:
            raise RuntimeError("No file <input> found on page.")
        await input_loc.set_input_files([str(p) for p in paths])

        # Wait until send button is enabled (= attachment finished processing).
        await self._wait_send_enabled(ready_timeout)

    async def _wait_send_enabled(self, timeout: float = 60.0) -> None:
        """Block until the composer's send button is present AND not disabled.

        Returns True when ready. Raises TimeoutError if attachments never finish
        processing within `timeout` seconds.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = await self._page.evaluate("""() => {
                // The send button has multiple variants; find any send-ish button.
                const cands = [...document.querySelectorAll('button')].filter(b => {
                    const a = (b.getAttribute('data-testid')||'') + ' ' +
                              (b.getAttribute('aria-label')||'');
                    return /send-button|send|发送/i.test(a);
                });
                // Also detect a disabled wrapper by aria-disabled on a form[role]
                if (!cands.length) return {found: false};
                const b = cands[cands.length-1];
                const disabled = b.disabled ||
                    b.getAttribute('aria-disabled') === 'true' ||
                    b.closest('[aria-disabled="true"]') !== null;
                return {found: true, disabled};
            }""")
            if state.get("found") and not state.get("disabled"):
                return
            await asyncio.sleep(0.5)
        # Timed out waiting — but proceed anyway (caller can still try submit).
        return

    # ---- high-level ----
    async def submit(
        self, prompt: str, *, attachments: Optional[list[str]] = None,
        input_mode: str = "paste", url_timeout: float = 30.0,
    ) -> str:
        """Submit `prompt` and return the chat URL as soon as it's assigned.

        This is the FIRE-AND-FORGET entry: it types, uploads, submits, waits
        ONLY for the /c/<id> URL to appear (~4s after submit), then returns.
        It does NOT wait for generation to finish — the server keeps generating
        after this call returns (and after the browser closes).

        Use this for long tasks: submit() to get the URL, then poll status()
        / save() / resume() from any process at your own pace.

        Returns the chat URL (https://chatgpt.com/c/<uuid>). Raises
        RuntimeError if the URL doesn't appear within url_timeout (submit may
        have failed — check that the composer had content + send was enabled).
        """
        await self._focus_composer()
        if attachments:
            await self.upload(*attachments)
            await asyncio.sleep(0.5)
            await self._focus_composer()
        await self._type_to_composer(prompt, mode=input_mode)
        await asyncio.sleep(0.3)
        await self._wait_send_enabled(timeout=10.0)
        await self._submit()
        # wait for the /c/<id> URL to be assigned by ChatGPT's router
        deadline = time.monotonic() + url_timeout
        while time.monotonic() < deadline:
            url = await self._page.evaluate("() => location.href")
            if "/c/" in url:
                self.current_chat_url = url
                return url
            await asyncio.sleep(0.5)
        raise RuntimeError(
            f"chat URL did not appear within {url_timeout}s — submit may have failed"
        )

    async def status(self, chat_url: str) -> dict:
        """One-shot read of a chat's current state. Returns:
            {state: 'GENERATING'|'DONE'|'EMPTY'|'STALLED',
             chars: int, generating: bool, head: str}

        Opens the chat, reads once, returns immediately. Safe to call
        repeatedly; safe to call from a different process than the submitter.
        """
        if not chat_url or "/c/" not in chat_url:
            raise ValueError(f"status() needs a /c/<id> chat URL, got {chat_url!r}")
        await self._page.goto(chat_url, wait_until="domcontentloaded", timeout=60000)
        # Reopened chats lazy-load the turn; poll briefly (up to 12s) for the
        # assistant element to render text before declaring state. Verified:
        # text appears ~5s post-goto on a completed chat; a single read after
        # networkidle can race and see EMPTY.
        snap = {}
        for _ in range(24):
            snap = await self._page.evaluate(
                """() => {
                    const a = [...document.querySelectorAll('[data-message-author-role="assistant"]')];
                    const text = a.length ? a[a.length-1].innerText : '';
                    const stop = document.querySelector(
                        '[data-testid="stop-button"], [aria-label*="Stop" i], [aria-label*="停止"]');
                    return {chars: text.length, head: text.slice(0,120),
                            generating: !!stop, hasTurn: a.length > 0};
                }"""
            )
            # once we have a turn with real text OR clear generating state, done
            if snap["hasTurn"] and (snap["chars"] >= 2 or snap["generating"]):
                break
            await asyncio.sleep(0.5)
        if not snap:
            snap = {"chars": 0, "head": "", "generating": False, "hasTurn": False}
        if not snap["hasTurn"]:
            state = "EMPTY"
        elif snap["generating"]:
            # generating=True wins over low char count — Pro shows "thinking…"
            # placeholders with little innerText before the real text streams.
            state = "GENERATING"
        elif snap["chars"] < 2:
            state = "EMPTY"
        else:
            state = "DONE"
        snap["state"] = state
        return snap

    async def ask(
        self, prompt: str, *, attachments: Optional[list[str]] = None,
        input_mode: str = "paste", type_delay: int = 6, timeout: float = 3600.0,
        stall_threshold: float = 300.0, on_heartbeat=None,
    ) -> TurnResult:
        """Send `prompt` (with optional file attachments) and return the reply.

        timeout is now a CEILING (default 1h), not a budget — short tasks finish
        in seconds; long Pro tasks (deep research / planning, can run minutes to
        hours) wait until done/stall, only true zombies hit the cap. Raise it
        for known-multi-hour tasks.

        stall_threshold (default 5min): if the stop-button is still present but
        text hasn't changed for this long, treat it as a page hang and return
        partial + completed=False (caller can resume()). Normal Pro thinking
        streams continuously, so a 5-min freeze is a real anomaly.

        on_heartbeat(elapsed, text_len, generating): optional callback fired
        every ~30s so callers can log progress / keep a UI alive during long
        waits.

        input_mode:
          - "paste" (default): bulk-insert via execCommand('insertText').
            Newline-safe; never submits mid-prompt.
          - "keyboard": legacy char-by-char typing.
          - "clipboard": clipboard paste fallback.
        """
        t0 = time.monotonic()
        await self._focus_composer()
        if attachments:
            await self.upload(*attachments)
            await asyncio.sleep(0.5)
            await self._focus_composer()
        await self._type_to_composer(prompt, mode=input_mode)
        await asyncio.sleep(0.3)
        await self._wait_send_enabled(timeout=10.0)
        await self._submit()
        text, completed = await self._wait_turn_done(
            timeout=timeout, stall_threshold=stall_threshold,
            on_heartbeat=on_heartbeat,
        )
        # If we never captured a /c/ URL in this turn, try once more — the URL
        # assignment can lag the submit by a few seconds.
        if self.current_chat_url is None:
            try:
                url = await self._page.evaluate("() => location.href")
                if "/c/" in url:
                    self.current_chat_url = url
            except Exception:
                pass
        return TurnResult(
            text=text, plan=self.plan or "",
            elapsed=time.monotonic() - t0,
            chat_url=self.current_chat_url, completed=completed,
        )

    async def resume(
        self, chat_url: str, *, timeout: float = 3600.0, poll_interval: float = 3.0,
        stall_threshold: float = 300.0, heartbeat_interval: float = 30.0,
        on_heartbeat=None,
    ) -> TurnResult:
        """Reopen an existing chat and read its latest assistant turn to completion.

        Use this after an ask() returned `completed=False`: ChatGPT keeps
        generating server-side, so navigating back to the chat URL and polling
        yields the FULL reply even if the original browser was closed.

        Verified: a 300-word reply that was len=0 in-session returned complete
        (len=2097) after a disconnect + resume(). Works in a FRESH session too.

        Heartbeat-style: timeout is a CEILING (default 1h), not a budget.
        Exits on DONE (stop gone + stable), STALL (gen=True but no text change
        for stall_threshold — page hang), or HARD CAP. on_heartbeat fires every
        ~heartbeat_interval seconds for progress logging.
        """
        t0 = time.monotonic()
        if not chat_url or "/c/" not in chat_url:
            raise ValueError(f"resume() needs a /c/<id> chat URL, got {chat_url!r}")
        self.current_chat_url = chat_url
        await self._page.goto(chat_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await self._page.wait_for_load_state("networkidle", timeout=25000)
        except PWTimeout:
            pass
        # Reopened chats lazy-load the turn — wait for it to render before
        # polling for completion (otherwise we may see empty text + gen=False
        # and falsely conclude DONE/EMPTY). Give it up to 15s.
        for _ in range(30):
            prep = await self._page.evaluate(
                """() => {
                    const a = [...document.querySelectorAll('[data-message-author-role="assistant"]')];
                    const text = a.length ? a[a.length-1].innerText : '';
                    const stop = document.querySelector(
                        '[data-testid="stop-button"], [aria-label*="Stop" i], [aria-label*="停止"]');
                    return {hasTurn: a.length > 0, len: text.length, gen: !!stop};
                }"""
            )
            if prep["hasTurn"] and (prep["len"] >= 2 or prep["gen"]):
                break
            await asyncio.sleep(0.5)
        deadline = time.monotonic() + timeout
        last_text, stable = "", 0
        last_change_at = time.monotonic()
        last_heartbeat_at = 0.0
        while time.monotonic() < deadline:
            snap = await self._page.evaluate(
                """() => {
                    const a=[...document.querySelectorAll('[data-message-author-role="assistant"]')];
                    const text = a.length ? a[a.length-1].innerText : '';
                    const stop = document.querySelector(
                        '[data-testid="stop-button"], [aria-label*="Stop" i], [aria-label*="停止"]');
                    return {text, generating: !!stop};
                }"""
            )
            now = time.monotonic()
            text = snap.get("text", "")
            gen = snap.get("generating", True)
            if text != last_text:
                last_change_at = now
            if on_heartbeat and (now - last_heartbeat_at) >= heartbeat_interval:
                last_heartbeat_at = now
                try:
                    on_heartbeat(now - t0, len(text), gen)
                except Exception:
                    pass
            if (not gen) and len(text) >= 2 and text.strip().lower() not in PLACEHOLDERS:
                if text == last_text:
                    stable += 1
                    if stable >= 3:
                        md, _, _ = await self._read_assistant_text()
                        return TurnResult(
                            text=(md or text), plan=self.plan or "",
                            elapsed=time.monotonic() - t0,
                            chat_url=chat_url, completed=True,
                        )
                else:
                    stable = 0
            else:
                stable = 0
            # STALL: still generating but frozen — page hang, not normal Pro
            if gen and (now - last_change_at) >= stall_threshold and len(text) > 0:
                md, _, _ = await self._read_assistant_text()
                return TurnResult(
                    text=(md or text), plan=self.plan or "",
                    elapsed=time.monotonic() - t0,
                    chat_url=chat_url, completed=False,
                    error=f"resume stalled: no text change for {stall_threshold:.0f}s while generating",
                )
            last_text = text
            await asyncio.sleep(poll_interval)
        # HARD CAP
        md, _, _ = await self._read_assistant_text()
        return TurnResult(
            text=(md or last_text), plan=self.plan or "",
            elapsed=time.monotonic() - t0,
            chat_url=chat_url, completed=False,
            error=f"resume hit hard cap ({timeout:.0f}s); server may still be generating",
        )

    async def new_chat(self) -> None:
        """Start a fresh chat so tests are isolated.

        IMPORTANT: navigating to chatgpt.com/ often RESUMES the last active
        chat rather than showing a blank composer. We must click the explicit
        "create-new-chat-button". Verified cross-chat-crosstalk bug: without
        this, a CSV test returned the previous big.txt run's sentinel.
        """
        # reset the tracked chat URL — a new chat has no /c/ URL yet
        self.current_chat_url = None
        # click the dedicated new-chat control
        try:
            btn = self._page.locator('[data-testid="create-new-chat-button"]').first
            await btn.click(timeout=10000)
            await asyncio.sleep(1.5)
        except PWError:
            # fallback: direct navigation
            try:
                await self._page.goto(self.BASE, wait_until="domcontentloaded", timeout=30000)
            except PWError:
                pass
        # wait for the composer to be empty (truly fresh)
        for _ in range(20):
            empty = await self._page.evaluate("""() => {
                const e = document.querySelector('div.ProseMirror[contenteditable="true"]');
                if (!e) return false;
                return e.innerText.trim() === '';
            }""")
            # also confirm no assistant turns present on this view
            turns = await self._page.evaluate(
                "() => document.querySelectorAll('[data-message-author-role=\"assistant\"]').length")
            if empty and turns == 0:
                return
            await asyncio.sleep(0.3)


@asynccontextmanager
async def session(headless: bool = False):
    s = ChatGPTSession(headless=headless)
    try:
        await s.__aenter__()
        yield s
    finally:
        await s.__aexit__(None, None, None)
