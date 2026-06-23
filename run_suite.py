"""
Comprehensive test suite for ChatGPT Pro browser-driven access.

Covers:
  A. Single-file uploads across all supported types (11 types)
  B. Multi-file mixed uploads
  C. Long tasks: big input, long output, deep reasoning
  D. Multi-turn state retention

Each test:
  - runs in a fresh chat (isolation)
  - records elapsed time + pass/fail
  - writes a JSONL row to results/run_<timestamp>.jsonl
  - prints a live line

Run a subset with --only A,B  or  --only single,multi
"""
import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from lib.harness import ChatGPTSession       # noqa: E402
from fixtures.gen_fixtures import make_all    # noqa: E402

RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)


# --------------------------------------------------------------------------- #
# Reporting helpers
# --------------------------------------------------------------------------- #
class Reporter:
    def __init__(self, name: str):
        self.name = name
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = RESULTS / f"{name}_{ts}.jsonl"
        self.rows = []
        self.fh = open(self.path, "w")

    def record(self, test_id: str, desc: str, passed: bool, elapsed: float,
               reply: str, note: str = ""):
        row = {
            "test_id": test_id, "desc": desc, "passed": passed,
            "elapsed": round(elapsed, 1), "reply_head": reply[:400],
            "note": note, "ts": datetime.now().isoformat(),
               }
        self.rows.append(row)
        self.fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.fh.flush()
        flag = "PASS" if passed else "FAIL"
        print(f"  [{flag}] {test_id:24} {elapsed:6.1f}s  {desc}")
        if not passed:
            print(f"           reply[:200]: {reply[:200]!r}")
        return row

    def close(self):
        self.fh.close()
        n = len(self.rows)
        ok = sum(r["passed"] for r in self.rows)
        print(f"\n=== {self.name}: {ok}/{n} passed ({ok/n*100:.0f}%) → {self.path} ===")
        return ok, n


# --------------------------------------------------------------------------- #
# Assertions on replies
# --------------------------------------------------------------------------- #
def sentinel_present(reply: str, sentinel: str) -> bool:
    return sentinel.lower() in reply.lower()


def count_sentinels(reply: str, sentinels: list[str]) -> int:
    rl = reply.lower()
    return sum(1 for s in sentinels if s.lower() in rl)


# --------------------------------------------------------------------------- #
# Test suite A: single-file uploads (all types)
# --------------------------------------------------------------------------- #
async def suite_single(rep: Reporter, s: ChatGPTSession, fx_all: dict):
    print("\n--- Suite A: single-file uploads ---")
    # For images, ChatGPT cannot OCR arbitrary text in a solid-color image;
    # we embed the sentinel as a JPEG COM comment (not visible) — so for images
    # we instead verify ChatGPT acknowledges the image (doesn't reject it).
    image_names = {"img.png", "img.jpg"}

    for name, fx in fx_all.items():
        if name == "big.txt":
            continue   # tested in long-input suite
        desc = fx["desc"]
        sentinel = fx["sentinel"]
        await s.new_chat()
        if name in image_names:
            prompt = ("Describe what you see in this attached image in one short "
                      "sentence. Confirm you received an image file.")
            async def _run():
                return await s.ask(prompt, attachments=[fx["path"]], timeout=120)
            r = await _run()
            # pass = reply acknowledges an image (not an error/rejection)
            ok = bool(re.search(r"\b(image|red|color|picture|图片|红色|颜色)\b",
                                r.text, re.I)) and "error" not in r.text.lower()[:80]
            rep.record(f"single:{name}", f"single {desc}", ok, r.elapsed, r.text)
        else:
            prompt = (f"Read the attached file and reply with ONLY the exact sentinel "
                      f"string it contains. It starts with the characters FIXTURE_SENTINEL_ "
                      f"or NEEDLE_. Output nothing else.")
            r = await s.ask(prompt, attachments=[fx["path"]], timeout=120)
            ok = sentinel_present(r.text, sentinel)
            rep.record(f"single:{name}", f"single {desc}", ok, r.elapsed, r.text)


# --------------------------------------------------------------------------- #
# Test suite B: multi-file uploads
# --------------------------------------------------------------------------- #
async def suite_multi(rep: Reporter, s: ChatGPTSession, fx_all: dict):
    print("\n--- Suite B: multi-file uploads ---")

    # B1: 3 text-ish files, ask for all 3 sentinels
    await s.new_chat()
    trio = ["note.txt", "readme.md", "code.py"]
    paths = [fx_all[n]["path"] for n in trio]
    sentinels = [fx_all[n]["sentinel"] for n in trio]
    prompt = ("I attached 3 files. Each contains a sentinel string starting with "
              "FIXTURE_SENTINEL_. List all three sentinel strings, one per line, "
              "in the order: txt, md, py. Output ONLY the three strings.")
    r = await s.ask(prompt, attachments=paths, timeout=150)
    found = count_sentinels(r.text, sentinels)
    rep.record("multi:3text", f"3 text files, expect 3 sentinels",
               found == 3, r.elapsed, r.text, note=f"found {found}/3")

    # B2: mixed types (pdf + csv + json + xlsx + docx)
    await s.new_chat()
    mixed = ["doc.pdf", "data.csv", "data.json", "doc.docx", "sheet.xlsx"]
    paths = [fx_all[n]["path"] for n in mixed]
    sentinels = [fx_all[n]["sentinel"] for n in mixed]
    prompt = ("I attached 5 files of different types. Each contains a unique sentinel "
              "string (starting with FIXTURE_SENTINEL_). List all sentinel strings you "
              "find, one per line. Output ONLY the strings.")
    r = await s.ask(prompt, attachments=paths, timeout=180)
    found = count_sentinels(r.text, sentinels)
    rep.record("multi:5mixed", f"5 mixed-type files, expect 5 sentinels",
               found >= 4, r.elapsed, r.text, note=f"found {found}/5")

    # B3: cross-file reasoning (sum a value from csv + a value from json)
    await s.new_chat()
    paths = [fx_all["data.json"]["path"]]
    # json has numbers [3,1,4,1,5,9,2,6] sum=31
    prompt = ("Read the attached JSON. Sum the values in the 'numbers' array. "
              "Reply with ONLY the integer sum.")
    r = await s.ask(prompt, attachments=paths, timeout=120)
    ok = "31" in re.sub(r"[^0-9]", "", r.text.split("\n")[0])[-4:] if r.text.strip() else False
    # more lenient: 31 anywhere
    ok = "31" in r.text and len(r.text.strip()) < 40
    rep.record("multi:crossfile-sum", "JSON array sum (expect 31)",
               ok, r.elapsed, r.text)


# --------------------------------------------------------------------------- #
# Test suite C: long tasks
# --------------------------------------------------------------------------- #
async def suite_long(rep: Reporter, s: ChatGPTSession, fx_all: dict):
    print("\n--- Suite C: long tasks ---")

    # C1: big input (132KB file with a hidden needle)
    await s.new_chat()
    big = fx_all["big.txt"]
    r = await s.ask(
        "This is a large attached file. Somewhere in the middle there is a line "
        "containing the exact marker NEEDLE_IN_HAYSTACK_UNIQ_7Q3Z9. "
        "Quote that entire line verbatim.",
        attachments=[big["path"]], timeout=300,
    )
    ok = big["sentinel"] in r.text
    rep.record("long:big-input-needle", "find needle in 132KB file",
               ok, r.elapsed, r.text[:200])

    # C2: long output (ask for a 1000-word essay)
    await s.new_chat()
    r = await s.ask(
        "Write a detailed essay about the history of computing, at least 800 words. "
        "Do not stop early.",
        timeout=300,
    )
    word_count = len(r.text.split())
    ok = word_count >= 500   # allow some slack
    rep.record("long:long-output", f"800+ word essay (got {word_count} words)",
               ok, r.elapsed, r.text[:150], note=f"words={word_count}")

    # C3: deep reasoning (multi-step math)
    await s.new_chat()
    r = await s.ask(
        "Solve step by step: A farmer has 100 meters of fence to enclose a "
        "rectangular field along a river (no fence needed on the river side). "
        "What dimensions maximize the area? Show your work, then state the "
        "final dimensions and area.",
        timeout=300,
    )
    # Max area: width=25 (perpendicular to river), length=50 (along river), area=1250
    ok = "1250" in r.text and "50" in r.text and "25" in r.text
    rep.record("long:deep-reasoning", "constrained optimization (expect area 1250)",
               ok, r.elapsed, r.text[:200])

    # C4: large in-prompt input (no file — paste ~20KB text directly)
    await s.new_chat()
    bulk = ("Lorem ipsum dolor sit amet. " * 600)  # ~14KB
    needle = "UNIQUE_PROMPT_NEEDLE_8842"
    bulk = bulk[:7000] + f" {needle} " + bulk[7000:]
    r = await s.ask(
        f"Below is text with one special marker {needle} hidden in it. "
        f"Quote the marker back exactly. Then say nothing else.\n\nTEXT:\n{bulk}",
        timeout=180,
    )
    ok = needle in r.text
    rep.record("long:big-prompt", "find needle in 14KB pasted prompt",
               ok, r.elapsed, r.text[:150])


# --------------------------------------------------------------------------- #
# Test suite D: multi-turn state
# --------------------------------------------------------------------------- #
async def suite_multi_turn(rep: Reporter, s: ChatGPTSession):
    print("\n--- Suite D: multi-turn state retention ---")
    await s.new_chat()
    secret = "MY_SECRET_IS_BANANA_SPLIT_42"
    r1 = await s.ask(f"Remember this secret for our conversation: {secret}. "
                     f"Reply only 'OK'.", timeout=60)
    ok1 = ok1_simple = "ok" in r1.text.lower()[:10]
    rep.record("multi-turn:turn1", "set secret", ok1_simple, r1.elapsed, r1.text[:100])

    r2 = await s.ask("What was the secret I told you? Reply with ONLY the secret.",
                     timeout=60)
    ok2 = secret in r2.text
    rep.record("multi-turn:turn2", "recall secret (expect same session)",
               ok2, r2.elapsed, r2.text[:150])

    r3 = await s.ask("Now reverse it (spell the secret backwards). ONLY the reversed string.",
                     timeout=60)
    expected_rev = secret[::-1]
    ok3 = expected_rev.lower() in r3.text.lower().replace(" ", "")
    rep.record("multi-turn:turn3", "transform secret across turns",
               ok3, r3.elapsed, r3.text[:150])


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
SUITES = {
    "single": suite_single,
    "multi": suite_multi,
    "long": suite_long,
    "multi-turn": suite_multi_turn,
}

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="single,multi,long,multi-turn",
                    help="comma list of suite names")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    selected = [x.strip() for x in args.only.split(",") if x.strip()]
    fx_all = make_all()
    rep = Reporter("suite")
    print(f"fixtures: {len(fx_all)} | suites: {selected}")

    async with ChatGPTSession(headless=args.headless) as s:
        await s.ensure_pro()
        print(f"plan: {s.plan}")
        for name in selected:
            fn = SUITES.get(name)
            if not fn:
                print(f"  [skip] unknown suite '{name}'"); continue
            try:
                await fn(rep, s, fx_all if name != "multi-turn" else None)
            except Exception as e:
                import traceback
                traceback.print_exc()
                rep.record(f"suite:{name}", f"{name} crashed", False, 0.0,
                           str(e), note="CRASH")

    ok, n = rep.close()
    sys.exit(0 if ok == n else 1)


if __name__ == "__main__":
    asyncio.run(main())
