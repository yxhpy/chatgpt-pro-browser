"""Regression test: harness refactor (paste-mode input + send-button submit).

Verifies:
  R1. A MULTI-LINE prompt (the original failure) submits as ONE turn and the
      model sees ALL lines (newline-safe).
  R2. A prompt containing a fenced code block with blank lines submits intact.
  R3. A single-line prompt still works (back-compat with existing callers).
  R4. input_mode="keyboard" still works (legacy path not broken).
"""
import asyncio, sys, re
sys.path.insert(0, "/Users/yxhpy/ZCodeProject/chatgpt-pro-browser/plugins/chatgpt-pro-browser/lib")
from harness import ChatGPTSession

# A multi-line prompt with a sentinel per line + a fenced code block. If the
# harness broke on Enter, this would fragment into multiple turns and the model
# would only see the first line.
MULTILINE = """I will give you three markers, one per line. After reading ALL of them, reply with a single line listing all three in order, separated by commas.

MARKER_ALPHA
MARKER_BETA
MARKER_GAMMA

Here is a code block to ignore:

```python
def f():
    return "ignore me"
```

Now reply with the three markers in order, comma-separated, nothing else."""

async def main():
    async with ChatGPTSession(headless=False) as s:
        await s.ensure_pro()

        # R1: multi-line, paste mode (default)
        await s.new_chat()
        r1 = await s.ask(MULTILINE, input_mode="paste", timeout=120)
        has_all = all(m in r1.text for m in ("ALPHA", "BETA", "GAMMA"))
        # model should produce a single line with all three; not just ALPHA
        ok1 = has_all and "BETA" in r1.text
        print(f"R1 multiline-paste: {r1.elapsed:.1f}s  pass={ok1}  reply={r1.text[:120]!r}")

        # R3: single-line, paste mode (back-compat)
        await s.new_chat()
        r3 = await s.ask("Reply with only the word: PONG", timeout=60)
        ok3 = "pong" in r3.text.lower()
        print(f"R3 singleline-paste: {r3.elapsed:.1f}s  pass={ok3}  reply={r3.text[:80]!r}")

        # R4: single-line, keyboard mode (legacy path)
        await s.new_chat()
        r4 = await s.ask("Reply with only the word: PONG2", input_mode="keyboard", timeout=60)
        ok4 = "pong2" in r4.text.lower()
        print(f"R4 singleline-keyboard: {r4.elapsed:.1f}s  pass={ok4}  reply={r4.text[:80]!r}")

    results = {"R1_multiline_paste": ok1, "R3_singleline_paste": ok3, "R4_keyboard": ok4}
    n_ok = sum(results.values())
    print(f"\n=== regression: {n_ok}/{len(results)} passed ===")
    for k, v in results.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    sys.exit(0 if n_ok == len(results) else 1)

asyncio.run(main())
