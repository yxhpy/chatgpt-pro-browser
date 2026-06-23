#!/usr/bin/env python3
"""status.py — peek at a ChatGPT chat's current state (one-shot, non-blocking).

ATOM 2 of 3 (submit / status / save). Opens the chat, reads once, prints the
state, exits. Safe to call repeatedly; safe from a different process than the
submitter. Does NOT wait for completion.

Usage:
    python3 status.py <chat_url>
    python3 status.py https://chatgpt.com/c/<uuid> --headless

States reported:
    GENERATING  (stop button visible — still thinking; shows current char count)
    DONE        (completed)
    EMPTY       (no assistant turn yet — task may not have started)

Output (stdout, pipe-friendly):
    <STATE> chars=<N> generating=<true|false>
    <first 120 chars of the reply>
"""
import argparse
import asyncio
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))

from harness import ChatGPTSession  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="One-shot peek at a ChatGPT chat's state.",
    )
    ap.add_argument("chat_url", help="https://chatgpt.com/c/<uuid>")
    ap.add_argument("--no-pro", action="store_true")
    ap.add_argument("--headless", action="store_true", default=True)
    args = ap.parse_args()

    if "/c/" not in args.chat_url:
        print(f"[error] URL must be https://chatgpt.com/c/<uuid>, got {args.chat_url!r}",
              file=sys.stderr)
        return 2

    async with ChatGPTSession(headless=args.headless) as s:
        if not args.no_pro:
            await s.ensure_pro()
        snap = await s.status(args.chat_url)
    # stdout: machine-parseable single line + head
    print(f"{snap['state']} chars={snap['chars']} generating={snap['generating']}")
    print(snap["head"])
    return 0 if snap["state"] != "EMPTY" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
