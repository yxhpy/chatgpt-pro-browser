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
REPO_ROOT = SKILL_DIR.parent.parent                    # plugin root (lib/ lives here)

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
    timeout: float = 600.0,
) -> tuple[str, Path]:
    """Run the full pipeline. Returns (final_plan_text, saved_path).

    Dependency model: the planner OWNS the planning knowledge (templates,
    output contract, prompt assembly) and NOTHING else. It does not import the
    browser harness, open a browser, or know how Pro is reached. It hands the
    assembled prompt to the BROWSER skill's `ask.py` (its supported CLI) via
    subprocess, and treats the returned text as opaque. Two skills, one job
    each — process-isolated, no shared Python state.
    """
    import subprocess

    prompt = build_prompt(plan_type, goal, context_files, REPO_ROOT)
    text = await _ask_via_browser_skill(prompt, headless, require_pro, timeout)

    if refine:
        cue = build_refinement_cue(plan_type, REPO_ROOT)
        refined = await _ask_via_browser_skill(cue, headless, require_pro, timeout)
        # prefer the refined version, but keep round 1 if round 2 looks broken
        if refined and len(refined) > len(text) * 0.5:
            text = refined
    path = save_plan(text, goal, plan_type, REPO_ROOT, out_path)
    return text, path


async def _ask_via_browser_skill(
    prompt: str, headless: bool, require_pro: bool, timeout: float,
) -> str:
    """Call the browser skill's ask.py as a subprocess; return its stdout.

    This is the SOLE point of contact between the two skills. If ask.py's CLI
    contract changes (args/output), only this function needs updating. The
    browser skill handles: browser lifecycle, Pro verification, downgrade
    guard, paste-mode input, resume loop, heartbeat logging. Planner sees none
    of that — just the final reply text.
    """
    import subprocess
    # the browser skill lives next door: skills/chatgpt-pro-browser/scripts/ask.py
    BROWSER_ASK = (SCRIPT_DIR.parent.parent / "chatgpt-pro-browser" / "scripts"
                   / "ask.py")
    if not BROWSER_ASK.exists():
        raise FileNotFoundError(
            f"browser skill ask.py not found at {BROWSER_ASK} — install the "
            f"chatgpt-pro-browser plugin/skill first")
    cmd = [sys.executable, str(BROWSER_ASK), prompt,
           "--input-mode", "paste", "--timeout", str(timeout)]
    if headless:
        cmd.append("--headless")
    if not require_pro:
        cmd.append("--no-pro")
    # heartbeat: ask.py prints [resume]/[warn] to stderr; surface it live
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout_b, stderr_b = await proc.communicate()
    if proc.returncode != 0:
        sys.stderr.write(stderr_b.decode("utf-8", "replace"))
        raise RuntimeError(
            f"ask.py exited {proc.returncode} — see stderr above")
    # surface any [resume]/[warn] progress lines from the browser skill
    err = stderr_b.decode("utf-8", "replace")
    for line in err.splitlines():
        if line.startswith("[resume]") or line.startswith("[warn]"):
            print(line, file=sys.stderr)
    return stdout_b.decode("utf-8", "replace").rstrip("\n")


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
