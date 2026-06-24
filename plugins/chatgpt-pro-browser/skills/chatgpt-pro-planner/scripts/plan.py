#!/usr/bin/env python3
"""plan.py — generate an executable engineering plan via ChatGPT Pro.

Usage:
    python3 plan.py <dev|test|refactor|bugfix> "<goal>" [options]

Options:
    --context <file>     attach a context file (repeatable; specs/source/README)
    --out <path>         output path (default: docs/superpowers/plans/YYYY-MM-DD-<slug>-<type>.md)
    --no-refine          skip the second refinement round
    --no-pro             don't require Pro plan (allow Plus/Free)
    --headless           run Chrome headless
    --timeout <sec>      per-turn timeout (default 300; deep reasoning needs it)
    --print              also print the final plan to stdout

This script depends on lib/harness.py (the chatgpt-pro-browser harness).
It is import-safe: the functions build_prompt / build_refinement_cue / save_plan
can be reused from other code without launching a browser.

Examples:
    python3 plan.py dev "Add streaming support to lib/harness.py" --context lib/harness.py
    python3 plan.py test "Cover the cookie-decryption path" --context lib/harness.py
    python3 plan.py bugfix "Upload hangs when send button stays disabled" --context lib/harness.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import date
from pathlib import Path

# Resolve paths: this script is at skills/chatgpt-pro-planner/scripts/plan.py
SCRIPT_DIR = Path(__file__).resolve().parent          # .../scripts
SKILL_DIR = SCRIPT_DIR.parent                          # .../chatgpt-pro-planner
REPO_ROOT = SKILL_DIR.parent.parent                    # repo root
LIB_DIR = REPO_ROOT / "lib"
sys.path.insert(0, str(LIB_DIR))

PLAN_TYPES = ("dev", "test", "refactor", "bugfix")
REFS_DIR = SKILL_DIR / "references"


# --------------------------------------------------------------------------- #
# Prompt construction (pure functions, no browser needed — unit-testable)
# --------------------------------------------------------------------------- #
def _read_ref(name: str) -> str:
    p = REFS_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"missing reference file: {p}")
    return p.read_text(encoding="utf-8")


def _slugify(text: str, maxlen: int = 50) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (s[:maxlen].rstrip("-") or "plan")


def _extract_role_block(template_md: str) -> str:
    """Pull the fenced system-prefix block from a <type>-template.md."""
    m = re.search(r"```\n(You are[\s\S]*?)```", template_md)
    if not m:
        # fall back to the Role & Instructions paragraph
        m = re.search(r"## Role & Instructions[^\n]*\n\n([\s\S]*?)\n## ", template_md)
        if m:
            return m.group(1).strip()
        raise ValueError("could not find role block in template")
    return m.group(1).strip()


def _extract_refinement_cue(template_md: str) -> str:
    """Pull the 'Refinement cue (turn 2)' fenced block from a template."""
    m = re.search(r"## Refinement cue[^\n]*\n+```\n([\s\S]*?)```", template_md)
    if not m:
        # generic fallback
        return ("Review your plan against the output contract in <OUTPUT_CONTRACT>: "
                "every requirement mapped to a task, no forbidden placeholders, "
                "consistent names/signatures, atomic steps. Fix any issues and "
                "output the full corrected plan.")
    return m.group(1).strip()


def build_prompt(
    plan_type: str,
    goal: str,
    context_files: list[str] | None = None,
    repo_root: str | Path | None = None,
) -> str:
    """Assemble the round-1 prompt: role prefix + output contract + goal + context.

    Pure function — does not touch the browser. Importable & unit-testable.
    """
    if plan_type not in PLAN_TYPES:
        raise ValueError(f"plan_type must be one of {PLAN_TYPES}, got {plan_type!r}")
    template = _read_ref(f"{plan_type}-template.md")
    role = _extract_role_block(template)
    contract = _read_ref("output-contract.md")

    parts = [role, "", "<OUTPUT_CONTRACT>", contract, "</OUTPUT_CONTRACT>", ""]
    parts.append("## The request")
    parts.append(goal.strip())
    parts.append("")

    if context_files:
        parts.append("## Attached context (read these files before planning)")
        for i, f in enumerate(context_files, 1):
            label = f
            try:
                # try to include a short header so the model knows what each is
                label = os.path.relpath(f, repo_root) if repo_root else f
            except ValueError:
                pass
            parts.append(f"{i}. `{label}`")
        parts.append("")
        parts.append("Use the file contents (provided as attachments) as ground truth. "
                     "Cite exact paths and line numbers where relevant.")

    parts.append("\nNow produce the complete plan in the format above. Output ONLY the plan markdown.")
    return "\n".join(parts)


def build_refinement_cue(plan_type: str, repo_root: str | Path | None = None) -> str:
    """The round-2 prompt: ask Pro to self-review against the contract."""
    if plan_type not in PLAN_TYPES:
        raise ValueError(f"plan_type must be one of {PLAN_TYPES}")
    template = _read_ref(f"{plan_type}-template.md")
    return _extract_refinement_cue(template)


def save_plan(
    text: str,
    goal: str,
    plan_type: str,
    repo_root: str | Path | None = None,
    out_path: str | None = None,
) -> Path:
    """Write the plan text to docs/superpowers/plans/YYYY-MM-DD-<slug>-<type>.md.

    Strips a leading ```markdown fence if Pro wrapped the output.
    Returns the absolute path written.
    """
    root = Path(repo_root) if repo_root else REPO_ROOT
    if out_path:
        p = Path(out_path)
    else:
        slug = _slugify(goal)
        d = root / "docs" / "superpowers" / "plans"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{date.today().isoformat()}-{slug}-{plan_type}.md"

    body = text.strip()
    # strip common fence wrappers
    if body.startswith("```"):
        body = re.sub(r"^```(?:markdown|md)?\n", "", body)
        body = re.sub(r"\n```\s*$", "", body)
    # Normalize checkbox + bullet markers: Pro often emits `* [ ]` / `* item`
    # but downstream tools (executing-plans) require `- [ ]`. Convert asterisk
    # bullets to hyphen at line start so the saved plan always parses.
    body = re.sub(r"(?m)^\* (\[ \])", r"- \1", body)   # checkboxes
    body = re.sub(r"(?m)^\* (?!\[)", r"- ", body)       # plain bullets (not checkboxes)
    p.write_text(body + "\n", encoding="utf-8")
    return p.resolve()


# --------------------------------------------------------------------------- #
# Browser-driving entry point
# --------------------------------------------------------------------------- #
async def generate(
    plan_type: str,
    goal: str,
    context_files: list[str] | None = None,
    out_path: str | None = None,
    refine: bool = True,
    require_pro: bool = True,
    headless: bool = False,
    timeout: float = 300.0,
    input_mode: str = "paste",
) -> tuple[str, Path]:
    """Run the full pipeline. Returns (final_plan_text, saved_path).

    input_mode defaults to "paste" — plan prompts are large/multi-line (role
    prefix + output contract + goal + context), and paste-mode avoids the
    Enter-submits-early problem that char-by-char typing hits on newlines.

    Resume-safe: if a turn times out mid-generation (Pro plans are slow), we
    call resume() on the chat URL instead of giving up. ChatGPT keeps
    generating server-side, so we always get the full reply.
    """
    from harness import ChatGPTSession  # imported lazily so import of this module
                                         # doesn't require the harness on path
    prompt = build_prompt(plan_type, goal, context_files, REPO_ROOT)

    def _hb(elapsed, tlen, gen):
        """Heartbeat: log progress every ~30s so the user sees it's alive."""
        print(f"[heartbeat] {elapsed:.0f}s elapsed, {tlen} chars, generating={gen}",
              file=sys.stderr)

    async def _ask_or_resume(s, prompt_text):
        """ask(); if not completed (stall/hard-cap), keep resuming until done.

        No fixed retry cap — Pro planning can run minutes-to-hours. We only stop
        resuming when: the turn completes, OR resume returns an error that isn't
        'still generating' (e.g. page crashed), OR we've resumed 12 times (each
        resume waits up to `timeout`, so 12 × timeout is a sane absolute ceiling
        of ~12h — anything beyond that is almost certainly a real failure).
        """
        r = await s.ask(prompt_text, input_mode=input_mode, timeout=timeout,
                        on_heartbeat=_hb)
        attempts = 0
        # keep resuming while: not completed AND we have a chat URL AND the last
        # error looks like "still generating" (not a hard crash)
        while (not r.completed and r.chat_url and attempts < 12):
            attempts += 1
            err = (r.error or "")
            print(f"[resume] not done yet ({err or 'no error'}); "
                  f"resume attempt {attempts} on {r.chat_url}", file=sys.stderr)
            r = await s.resume(r.chat_url, timeout=timeout, on_heartbeat=_hb)
        return r

    async with ChatGPTSession(headless=headless) as s:
        if require_pro:
            await s.ensure_pro()
        await s.new_chat()
        r1 = await _ask_or_resume(s, prompt)
        text = r1.text
        if refine:
            cue = build_refinement_cue(plan_type, REPO_ROOT)
            r2 = await _ask_or_resume(s, cue)
            # prefer the refined version, but keep r1 if r2 looks empty/broken
            if r2.text and len(r2.text) > len(text) * 0.5:
                text = r2.text
    path = save_plan(text, goal, plan_type, REPO_ROOT, out_path)
    return text, path


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate an executable plan via ChatGPT Pro.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Plan types: dev, test, refactor, bugfix",
    )
    ap.add_argument("plan_type", choices=PLAN_TYPES, help="kind of plan")
    ap.add_argument("goal", help="the objective (quote it)")
    ap.add_argument("--context", "-c", action="append", default=[],
                    help="context file to attach (repeatable)")
    ap.add_argument("--out", default=None, help="output path")
    ap.add_argument("--no-refine", action="store_true", help="skip round-2 refinement")
    ap.add_argument("--no-pro", action="store_true", help="don't require Pro plan")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--input-mode", choices=("paste", "keyboard", "clipboard"),
                    default="paste",
                    help="composer fill mode (default paste — safe for large "
                         "multi-line plan prompts)")
    ap.add_argument("--print", action="store_true", help="also print plan to stdout")
    args = ap.parse_args()

    text, path = asyncio.run(generate(
        plan_type=args.plan_type,
        goal=args.goal,
        context_files=args.context or None,
        out_path=args.out,
        refine=not args.no_refine,
        require_pro=not args.no_pro,
        headless=args.headless,
        timeout=args.timeout,
        input_mode=args.input_mode,
    ))
    print(f"[saved] {path}", file=sys.stderr)
    if args.print:
        print(text)
    # hint at validation
    validator = SCRIPT_DIR / "validate_plan.py"
    print(f"[hint] validate: python3 {validator} {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
