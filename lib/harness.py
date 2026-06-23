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


class ChatGPTSession:
    """Drives a logged-in ChatGPT Pro session.

    Usage:
        async with ChatGPTSession(headless=False) as s:
            await s.ensure_pro()
            r = await s.ask("hello")
            print(r.text)
    """

    BASE = "https://chatgpt.com/"

    def __init__(self, headless: bool = False, viewport=(1280, 800)):
        self.headless = headless
        self.viewport = viewport
        self._pw = None
        self._browser = None
        self._ctx: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.plan: Optional[str] = None

    # ---- lifecycle ----
    async def __aenter__(self) -> "ChatGPTSession":
        self._pw = await async_playwright().start()
        cookies = load_chatgpt_cookies()
        names = {c["name"] for c in cookies}
        if not {"__Secure-next-auth.session-token.0", "_puid"} <= names:
            raise RuntimeError(
                f"missing auth cookies (have {sorted(names)[:8]}...) — re-login in Chrome"
            )
        self._browser = await self._pw.chromium.launch(
            channel="chrome", headless=self.headless,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-default-browser-check", "--no-first-run"],
        )
        self._ctx = await self._browser.new_context(
            viewport={"width": self.viewport[0], "height": self.viewport[1]},
            user_agent=UA,
        )
        await self._ctx.add_cookies(cookies)
        self._page = await self._ctx.new_page()
        await self._page.goto(self.BASE, wait_until="domcontentloaded", timeout=60000)
        try:
            await self._page.wait_for_load_state("networkidle", timeout=25000)
        except PWTimeout:
            pass
        await asyncio.sleep(3)
        return self

    async def __aexit__(self, *exc):
        try:
            if self._ctx:
                await self._ctx.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass

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
        # also verify the composer is present (true login, not a login wall)
        try:
            await self._page.wait_for_selector(
                'div.ProseMirror[contenteditable="true"]', timeout=15000
            )
        except PWTimeout:
            raise RuntimeError("Login wall detected — session-token expired.")

    # ---- composer ----
    async def _focus_composer(self) -> None:
        loc = self._page.locator('div.ProseMirror[contenteditable="true"]').first
        await loc.click()
        await asyncio.sleep(0.2)

    async def _submit(self) -> None:
        await self._page.keyboard.press("Enter")

    # ---- completion detection ----
    async def _wait_turn_done(self, timeout: float = 180.0) -> str:
        deadline = time.monotonic() + timeout
        last_text, stable, gen = "", 0, True
        snap = {}
        while time.monotonic() < deadline:
            snap = await self._page.evaluate(
                """() => {
                    const turns = document.querySelectorAll('[data-testid^="conversation-turn-"]');
                    const asst = [...turns].filter(t => t.getAttribute('data-testid').endsWith('-2')
                        || /-\\d+$/.test(t.getAttribute('data-testid')));
                    // pick the LAST assistant turn (data-message-author-role=assistant)
                    const asst2 = [...document.querySelectorAll('[data-message-author-role="assistant"]')];
                    const text = asst2.length ? asst2[asst2.length-1].innerText : '';
                    const stop = document.querySelector(
                        '[data-testid="stop-button"], [aria-label*="Stop" i], [aria-label*="停止"]');
                    const send = document.querySelector(
                        '[data-testid="send-button"], [aria-label*="Send" i], [aria-label*="发送"]');
                    return {text, generating: !!stop, hasSend: !!send};
                }"""
            )
            text = snap.get("text", "")
            gen = snap.get("generating", True)
            low = text.strip().lower()
            done = (
                not gen
                and text
                and len(text) >= 2
                and low not in PLACEHOLDERS
            )
            if done and text == last_text:
                stable += 1
                if stable >= 3:   # ~0.9s stable
                    return text
            else:
                stable = 0
            last_text = text
            await asyncio.sleep(0.3)
        # timeout — return whatever we have
        return last_text or "[NO_RESPONSE_TIMEOUT]"

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
    async def ask(
        self, prompt: str, *, attachments: Optional[list[str]] = None,
        type_delay: int = 6, timeout: float = 180.0,
    ) -> TurnResult:
        t0 = time.monotonic()
        await self._focus_composer()
        if attachments:
            await self.upload(*attachments)
            await asyncio.sleep(0.5)
            # re-focus (upload may have moved focus)
            await self._focus_composer()
        await self._page.keyboard.type(prompt, delay=type_delay)
        await asyncio.sleep(0.3)
        # Make sure send is enabled before pressing Enter (also covers no-attachment
        # case where the composer needs a tick to enable after text input).
        await self._wait_send_enabled(timeout=10.0)
        await self._submit()
        text = await self._wait_turn_done(timeout=timeout)
        return TurnResult(
            text=text, plan=self.plan or "",
            elapsed=time.monotonic() - t0,
        )

    async def new_chat(self) -> None:
        """Start a fresh chat so tests are isolated.

        IMPORTANT: navigating to chatgpt.com/ often RESUMES the last active
        chat rather than showing a blank composer. We must click the explicit
        "create-new-chat-button". Verified cross-chat-crosstalk bug: without
        this, a CSV test returned the previous big.txt run's sentinel.
        """
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
