#!/usr/bin/env python3
"""ask.py — quick CLI to send one prompt to ChatGPT Pro and print the reply.

Usage:
    python3 skills/chatgpt-pro-browser/scripts/ask.py "your prompt here"
    python3 .../ask.py "summarize this" --file doc.pdf --file data.csv
    python3 .../ask.py "hello" --no-pro   # don't require Pro plan
    python3 .../ask.py "hello" --headless

Stays in the session's repo so it can find lib/harness.py.
"""
import argparse
import asyncio
import os
import sys

# Resolve the repo root (parent of skills/chatgpt-pro-browser/scripts/)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "lib"))

from harness import ChatGPTSession  # noqa: E402


async def main():
    ap = argparse.ArgumentParser(description="Send one prompt to ChatGPT Pro.")
    ap.add_argument("prompt", help="the prompt text")
    ap.add_argument("--file", "-f", action="append", default=[],
                    help="attach a file (repeatable)")
    ap.add_argument("--no-pro", action="store_true",
                    help="don't require the Pro plan (allow Plus/Free)")
    ap.add_argument("--headless", action="store_true", help="run headless")
    ap.add_argument("--timeout", type=float, default=180,
                    help="max seconds to wait (default 180)")
    ap.add_argument("--new-chat", action="store_true", default=True,
                    help="start a fresh chat (default; isolated)")
    args = ap.parse_args()

    async with ChatGPTSession(headless=args.headless) as s:
        if not args.no_pro:
            await s.ensure_pro()
        else:
            plan = await s.current_plan()
            print(f"[plan] {plan}", file=sys.stderr)
        if args.new_chat:
            await s.new_chat()
        r = await s.ask(args.prompt, attachments=args.file or None,
                        timeout=args.timeout)
        print(r.text)


if __name__ == "__main__":
    asyncio.run(main())
