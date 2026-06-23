"""Resume regression test — single session, two checks, minimal quota.

Check 1 (happy path): a short ask() completes in-session → completed=True,
chat_url is set, reply is sane.
Check 2 (resume idempotency): resume(the same chat_url) returns the SAME
complete reply (no truncation, no duplication). Proves resume() is safe to
call even when the turn already finished.
"""
import asyncio, sys
sys.path.insert(0, "/Users/yxhpy/ZCodeProject/chatgpt-pro-browser/plugins/chatgpt-pro-browser/lib")
from harness import ChatGPTSession

async def main():
    async with ChatGPTSession(headless=False) as s:
        await s.ensure_pro()
        await s.new_chat()

        print("--- Check 1: short ask() completes in-session ---")
        r1 = await s.ask("Reply with only the word: BANANA", timeout=60)
        print(f"  completed={r1.completed}  chat_url={r1.chat_url}")
        print(f"  reply={r1.text[:60]!r}")
        c1 = r1.completed and r1.chat_url and "/c/" in r1.chat_url and "banana" in r1.text.lower()
        print(f"  CHECK 1: {'PASS' if c1 else 'FAIL'}")

        print("\n--- Check 2: resume(same url) returns same reply (idempotent) ---")
        r2 = await s.resume(r1.chat_url, timeout=60)
        print(f"  completed={r2.completed}  reply_len={len(r2.text)} (was {len(r1.text)})")
        print(f"  reply={r2.text[:60]!r}")
        c2 = r2.completed and r2.text.strip() == r1.text.strip()
        print(f"  CHECK 2: {'PASS' if c2 else 'FAIL'}")

    print(f"\n=== regression: {sum([c1,c2])}/2 passed ===")
    sys.exit(0 if c1 and c2 else 1)

asyncio.run(main())
