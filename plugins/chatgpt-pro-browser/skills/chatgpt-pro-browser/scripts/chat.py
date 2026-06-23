#!/usr/bin/env python3
"""chat.py — interactive shell for ChatGPT Pro, reusing the daemon browser.

A REPL that holds ONE ChatGPTSession open and runs commands in-process — no
per-command browser restart. Auto-starts the daemon if none is running.

Commands:
    ask <prompt>           send a prompt in the current chat, wait, print reply
    submit <prompt>        fire a prompt, print its chat URL, don't wait
    status [url]           peek at a chat (default: the last one you submitted)
    save [url] --out <f>   fetch a chat's result to a file (default: last)
    new                    start a fresh chat (clears context)
    plan                   exit to run: plan.py (handled by the planner skill)
    files                  show attached files for the next ask
    attach <path>          attach a file (repeatable; used by next ask/submit)
    clear                  clear attachments
    help                   show this list
    quit / exit            leave (daemon stays up if you started one)

If a chat URL is omitted for status/save, the last submit/ask URL is used.

Usage:
    python3 chat.py                # interactive
    python3 chat.py --headless     # interactive, headless daemon
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))

from harness import ChatGPTSession, daemon_alive, read_lock  # noqa: E402


class ChatShell:
    def __init__(self, session: ChatGPTSession):
        self.s = session
        self.last_url: str | None = None
        self.attachments: list[str] = []

    async def cmd_ask(self, args: list[str]):
        if not args:
            print("usage: ask <prompt>"); return
        prompt = " ".join(args)
        r = await self.s.ask(prompt, attachments=self.attachments or None,
                             timeout=3600)
        self.last_url = r.chat_url or self.last_url
        if r.completed:
            print(r.text)
        else:
            print(f"[not done] {r.chat_url} — run: status {r.chat_url}")
        self.attachments.clear()

    async def cmd_submit(self, args: list[str]):
        if not args:
            print("usage: submit <prompt>"); return
        prompt = " ".join(args)
        url = await self.s.submit(prompt, attachments=self.attachments or None)
        self.last_url = url
        print(url)
        self.attachments.clear()

    async def cmd_status(self, args: list[str]):
        url = args[0] if args else self.last_url
        if not url:
            print("no chat URL — submit/ask first, or: status <url>"); return
        snap = await self.s.status(url)
        print(f"{snap['state']} chars={snap['chars']} generating={snap['generating']}")
        print(snap["head"])

    async def cmd_save(self, args: list[str]):
        # parse --out
        out = None
        pos = []
        i = 0
        while i < len(args):
            if args[i] == "--out" and i + 1 < len(args):
                out = args[i+1]; i += 2
            else:
                pos.append(args[i]); i += 1
        url = pos[0] if pos else self.last_url
        if not url:
            print("no chat URL — submit/ask first, or: save <url> --out <file>"); return
        print(f"[save] waiting on {url}...", file=sys.stderr)
        r = await self.s.resume(url, timeout=3600)
        if out:
            Path(out).write_text(r.text, encoding="utf-8")
            print(f"[saved] {out} ({len(r.text)} chars, completed={r.completed})")
        else:
            print(r.text)

    async def cmd_new(self, args):
        await self.s.new_chat()
        self.last_url = None
        print("[new chat started]")

    async def cmd_attach(self, args):
        for a in args:
            if os.path.exists(a):
                self.attachments.append(a)
                print(f"[attached] {a}")
            else:
                print(f"[not found] {a}")

    async def cmd_files(self, args):
        print("attachments:", self.attachments or "(none)")

    async def cmd_clear(self, args):
        self.attachments.clear()
        print("[attachments cleared]")

    async def dispatch(self, line: str) -> bool:
        """Returns False to exit the loop."""
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        if not parts:
            return True
        cmd, args = parts[0], parts[1:]
        if cmd in ("quit", "exit", "q"):
            return False
        if cmd == "help":
            self._help(); return True
        handler = {
            "ask": self.cmd_ask, "submit": self.cmd_submit,
            "status": self.cmd_status, "save": self.cmd_save,
            "new": self.cmd_new, "attach": self.cmd_attach,
            "files": self.cmd_files, "clear": self.cmd_clear,
        }.get(cmd)
        if not handler:
            print(f"unknown command: {cmd} (try: help)"); return True
        try:
            await handler(args)
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)
        return True

    def _help(self):
        print(__doc__.split("Commands:")[1].split("Usage:")[0])


async def main() -> int:
    ap = argparse.ArgumentParser(description="Interactive ChatGPT Pro shell.")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--no-pro", action="store_true")
    args = ap.parse_args()

    # auto-start daemon if not running, then connect to it (one browser for
    # the whole session, no per-command restart)
    started_daemon = False
    if not await daemon_alive():
        print("[chat] no daemon running — starting one...", file=sys.stderr)
        import subprocess
        subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "daemon.py")]
            + (["--headless"] if args.headless else []),
            stdout=open("/tmp/cg-daemon.log", "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True)
        # wait for it
        for _ in range(60):
            await asyncio.sleep(1)
            if await daemon_alive():
                break
        else:
            print("[chat] daemon did not come up — see /tmp/cg-daemon.log",
                  file=sys.stderr)
            return 1
        started_daemon = True
        print("[chat] daemon ready.", file=sys.stderr)

    # connect to the daemon
    async with ChatGPTSession(headless=args.headless, connect_mode="connect") as s:
        if not args.no_pro:
            await s.ensure_pro()
        shell = ChatShell(s)
        print("ChatGPT Pro shell. Type 'help' for commands, 'quit' to exit.")
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, input, "chat> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not await shell.dispatch(line):
                break
    if started_daemon:
        print("[chat] leaving daemon running. Stop it with: close.py",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
