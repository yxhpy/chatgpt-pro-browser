#!/usr/bin/env python3
"""daemon.py — start a persistent Chrome for ChatGPT Pro, kept alive in background.

Launches a real Chrome with a CDP port, injects the login cookies, and STAYS
OPEN (does not exit). Other scripts (submit/status/save) detect it via the lock
file and connect_over_cdp() — so each call takes seconds, not ~15s cold start.

Usage:
    # foreground (see what it's doing, Ctrl-C to stop):
    python3 daemon.py

    # background (recommended — survives terminal close):
    nohup python3 daemon.py > /tmp/chatgpt-pro-daemon.log 2>&1 &

    # headless daemon:
    python3 daemon.py --headless

Once running:
    - submit/status/save auto-reuse it (connect_mode=auto by default).
    - check it's up:   python3 status.py --daemon   (or any status call is fast)
    - stop it:         python3 close.py

Lock file: ~/.chatgpt-pro-browser.lock  (records cdp_url + pid)
"""
import argparse
import asyncio
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))

from harness import ChatGPTSession, daemon_alive, read_lock  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="Start a persistent ChatGPT Pro Chrome daemon.",
    )
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--no-pro", action="store_true",
                    help="don't require the Pro plan")
    args = ap.parse_args()

    # already running?
    if await daemon_alive():
        d = read_lock()
        print(f"[daemon] already running: cdp={d['cdp_url']} pid={d['pid']}",
              file=sys.stderr)
        return 0

    print("[daemon] starting persistent Chrome...", file=sys.stderr)
    # connect_mode="daemon" => launch + open CDP + write lock + DON'T close on exit
    s = ChatGPTSession(headless=args.headless, connect_mode="daemon")
    await s.__aenter__()
    if not args.no_pro:
        await s.ensure_pro()
    print(f"[daemon] up. pid={__import__('os').getpid()} "
          f"cdp=http://127.0.0.1:9223", file=sys.stderr)
    print("[daemon] keeping browser alive. Ctrl-C or run close.py to stop.",
          file=sys.stderr)
    print("[daemon] submit/status/save will now reuse this browser.",
          file=sys.stderr)

    # block forever (until killed). The browser stays up.
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await s.close()
        print("[daemon] shut down.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
