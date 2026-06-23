#!/usr/bin/env python3
"""submit.py — fire a ChatGPT Pro task and print the chat URL, then exit.

ATOM 1 of 3 (submit / status / save). This does NOT wait for the reply — the
server keeps generating after this returns. Use status.py to poll progress and
save.py to fetch the final result.

Usage:
    python3 submit.py "your prompt"
    python3 submit.py "summarize this" -f doc.pdf -f data.csv
    python3 submit.py "long task" --headless

Output (stdout): the chat URL, e.g. https://chatgpt.com/c/<uuid>
                 (nothing else on stdout — pipe-friendly)
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))

from harness import ChatGPTSession  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="Submit a ChatGPT Pro task; print the chat URL; exit.",
    )
    ap.add_argument("prompt", help="the prompt text")
    ap.add_argument("--file", "-f", action="append", default=[],
                    help="attach a file (repeatable)")
    ap.add_argument("--no-pro", action="store_true",
                    help="don't require the Pro plan")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--input-mode", choices=("paste", "keyboard", "clipboard"),
                    default="paste")
    args = ap.parse_args()

    async with ChatGPTSession(headless=args.headless) as s:
        if not args.no_pro:
            await s.ensure_pro()
        await s.new_chat()
        url = await s.submit(
            args.prompt,
            attachments=args.file or None,
            input_mode=args.input_mode,
        )
        print(url)   # ONLY the URL on stdout — pipe-friendly
        print(f"[hint] status: python3 {__file__}/../status.py {url}", file=sys.stderr)
        print(f"[hint] save:   python3 {__file__}/../save.py {url} --out result.md",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
