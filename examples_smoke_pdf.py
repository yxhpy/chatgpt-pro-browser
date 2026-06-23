"""Smoke test: upload one PDF and verify ChatGPT reads its sentinel content."""
import asyncio, sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.harness import ChatGPTSession
from fixtures.gen_fixtures import make_all

async def main():
    fx = make_all()["doc.pdf"]
    async with ChatGPTSession(headless=False) as s:
        await s.ensure_pro()
        r = await s.ask(
            f"Read the attached PDF and reply with ONLY the sentinel string it contains (it starts with FIXTURE_SENTINEL_). Nothing else.",
            attachments=[fx["path"]],
            timeout=120,
        )
        print(f"[elapsed] {r.elapsed:.1f}s")
        print(f"[reply] {r.text[:300]}")
        ok = fx["sentinel"] in r.text
        print(f"[sentinel {fx['sentinel']} present] {ok}")
        print("SMOKE:", "PASS" if ok else "FAIL")

asyncio.run(main())
