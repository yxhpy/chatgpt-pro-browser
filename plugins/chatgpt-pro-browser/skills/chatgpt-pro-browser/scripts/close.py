#!/usr/bin/env python3
"""close.py — stop the persistent ChatGPT Pro Chrome daemon.

Connects to the running daemon (via the lock file), shuts down its browser,
and clears the lock. Safe to run when no daemon is up (no-op).

Usage:
    python3 close.py
"""
import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))

from harness import read_lock, clear_lock, LOCK_FILE  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="Stop the ChatGPT Pro daemon.")
    ap.add_argument("--force", action="store_true",
                    help="SIGKILL the daemon process if graceful stop fails")
    args = ap.parse_args()

    lock = read_lock()
    if not lock:
        print("[close] no daemon running (lock absent or stale).")
        clear_lock()   # tidy up a stale lock if any
        return 0

    pid = lock.get("pid")
    cdp = lock.get("cdp_url", "?")
    print(f"[close] stopping daemon pid={pid} cdp={cdp}", file=sys.stderr)

    # graceful: SIGTERM the daemon process (it catches it and calls close())
    killed = False
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            killed = True
        except (OSError, ProcessLookupError):
            pass

    if killed:
        # give it a moment to shut down
        import time
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except (OSError, ProcessLookupError):
                break
            time.sleep(0.25)

    # verify it's gone; SIGKILL if still alive and --force
    if pid:
        try:
            os.kill(pid, 0)
            if args.force:
                print("[close] process still alive; SIGKILL", file=sys.stderr)
                os.kill(pid, signal.SIGKILL)
            else:
                print("[close] process still alive (use --force to SIGKILL)",
                      file=sys.stderr)
        except (OSError, ProcessLookupError):
            pass

    clear_lock()
    print("[close] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
