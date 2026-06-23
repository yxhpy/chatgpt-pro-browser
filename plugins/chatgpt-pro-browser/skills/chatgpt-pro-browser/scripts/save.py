#!/usr/bin/env python3
"""save.py — fetch a ChatGPT chat's result and save it to a file.

ATOM 3 of 3 (submit / status / save). Polls the chat until generation finishes
(DONE) or stalls, then writes the full markdown reply to --out (or stdout).

Usage:
    # wait for completion, save to file:
    python3 save.py <chat_url> --out result.md

    # wait, print to stdout:
    python3 save.py <chat_url>

    # if already done, returns immediately:
    python3 save.py <chat_url> --out result.md --timeout 60

Uses heartbeat-style waiting (see harness.resume): short tasks finish fast,
long Pro tasks (minutes-to-hours) wait until done/stall. Prints a heartbeat
every ~30s on stderr so you can see it's alive.

Exit code: 0 on DONE, 1 on STALLED/timeout (partial saved if any).
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
        description="Fetch a ChatGPT chat's result; save to file or stdout.",
    )
    ap.add_argument("chat_url", help="https://chatgpt.com/c/<uuid>")
    ap.add_argument("--out", default=None,
                    help="output file path (default: stdout)")
    ap.add_argument("--no-pro", action="store_true")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--timeout", type=float, default=3600.0,
                    help="max seconds to wait (default 3600)")
    ap.add_argument("--poll", type=float, default=5.0,
                    help="poll interval (default 5s)")
    args = ap.parse_args()

    if "/c/" not in args.chat_url:
        print(f"[error] URL must be https://chatgpt.com/c/<uuid>, got {args.chat_url!r}",
              file=sys.stderr)
        return 2

    def hb(elapsed, tlen, gen):
        print(f"[heartbeat] {elapsed:.0f}s elapsed, {tlen} chars, generating={gen}",
              file=sys.stderr)

    async with ChatGPTSession(headless=args.headless) as s:
        if not args.no_pro:
            await s.ensure_pro()
        print(f"[save] polling {args.chat_url} (timeout {args.timeout:.0f}s)...",
              file=sys.stderr)
        r = await s.resume(args.chat_url, timeout=args.timeout,
                           poll_interval=args.poll, on_heartbeat=hb)

    if r.error:
        print(f"[warn] {r.error}", file=sys.stderr)
    if not r.text:
        print("[error] no text fetched", file=sys.stderr)
        return 1

    if args.out:
        Path(args.out).write_text(r.text, encoding="utf-8")
        print(f"[saved] {args.out} ({len(r.text)} chars, completed={r.completed})",
              file=sys.stderr)
    else:
        print(r.text)
    return 0 if r.completed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
