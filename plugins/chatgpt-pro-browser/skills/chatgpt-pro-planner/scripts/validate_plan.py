#!/usr/bin/env python3
"""validate_plan.py — hard format gate for superpowers markdown plans.

Checks a plan against the output-contract that executing-plans /
subagent-driven-development require. Exits 0 on PASS, 1 on FAIL, printing
a report to stderr.

Usage:
    python3 validate_plan.py <plan.md> [--strict]

--strict treats warnings (e.g. no `Run:` on a non-code step) as failures.

This is a pure static check — no browser, no Pro call — so it's safe in CI.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Forbidden placeholder phrases (case-insensitive substring match on a step line).
# These come straight from references/output-contract.md "No Placeholders".
FORBIDDEN = [
    r"\btbd\b", r"\btodo\b",
    r"implement later", r"fill in details",
    r"add (?:appropriate )?error handling", r"add validation",
    r"handle edge cases", r"cover edge cases",
    r"write (?:more |comprehensive )?tests?(?!_)",   # "write tests" w/o code
    r"similar to task",
]

# Header the downstream skills look for. Must be present verbatim.
REQUIRED_HEADER_LINE = "**For agentic workers:** REQUIRED SUB-SKILL"


def _sections(plan: str) -> list[tuple[str, int]]:
    """Return list of (heading_text, line_number) for all headings."""
    out = []
    for i, line in enumerate(plan.splitlines(), 1):
        if line.startswith("#"):
            out.append((line.strip(), i))
    return out


def validate(plan_text: str, strict: bool = False) -> tuple[bool, list[str], list[str]]:
    """Return (passed, errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    lines = plan_text.splitlines()

    # 1. Non-empty
    if not plan_text.strip():
        errors.append("plan is empty")
        return False, errors, warnings

    # 2. Title is an H1
    if not any(l.startswith("# ") for l in lines):
        errors.append("missing H1 title (must start with `# ...`)")

    # 3. Required header line present (verbatim)
    if REQUIRED_HEADER_LINE not in plan_text:
        errors.append(
            f"missing verbatim header line: '{REQUIRED_HEADER_LINE}' — "
            "downstream agents use it to route to the executor skill"
        )

    # 4. Goal present
    if not re.search(r"\*\*Goal:\*\*\s*\S", plan_text):
        errors.append("missing or empty '**Goal:**' field")

    # 5. At least one Task heading
    task_headings = [l for l in lines if re.match(r"^### Task \d+", l)]
    if not task_headings:
        errors.append("no `### Task N:` headings found — every plan needs tasks")

    # 6. Each Task has a Files block and at least one checkbox step
    #    Split the plan into per-task chunks by `### Task N:`.
    task_chunks = re.split(r"(?=^### Task \d+:)", plan_text, flags=re.M)
    task_chunks = [c for c in task_chunks if re.match(r"### Task \d+", c)]
    for chunk in task_chunks:
        title_m = re.match(r"(### Task \d+[^\n]*)", chunk)
        title = title_m.group(1) if title_m else "Task"
        if "**Files:**" not in chunk:
            errors.append(f"{title}: missing '**Files:**' block")
        if "- [ ]" not in chunk:
            errors.append(f"{title}: no `- [ ]` checkbox steps")

    # 7. At least one checkbox in the whole plan
    total_boxes = plan_text.count("- [ ]")
    if total_boxes == 0:
        errors.append("no `- [ ]` checkboxes anywhere — nothing to track")

    # 8. Placeholder scan on step lines
    placeholder_re = re.compile("|".join(FORBIDDEN), re.I)
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("- ["):
            m = placeholder_re.search(line)
            if m:
                errors.append(
                    f"line {i}: forbidden placeholder '{m.group(0)}' in step: {line.strip()[:80]}"
                )

    # 9. Verification steps should have Run:/Expected: (warning unless strict)
    #    A step is a "verification-ish" step if it mentions run/test/pytest/verify.
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("- [") and re.search(r"\b(run|test|pytest|verify|build)\b", line, re.I):
            # look at the next ~6 lines for Run: / Expected:
            window = "\n".join(lines[i:i+6])
            if "Run:" not in window:
                (errors if strict else warnings).append(
                    f"line {i}: verification step missing 'Run:' — {line.strip()[:60]}"
                )

    passed = not errors
    return passed, errors, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a superpowers markdown plan.")
    ap.add_argument("plan", help="path to the plan .md file")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings (missing Run: on verification steps) as failures")
    args = ap.parse_args()

    p = Path(args.plan)
    if not p.exists():
        print(f"[FAIL] file not found: {p}", file=sys.stderr)
        return 2
    text = p.read_text(encoding="utf-8")

    passed, errors, warnings = validate(text, strict=args.strict)
    label = "PASS" if passed else "FAIL"
    print(f"[{label}] {p}")
    for w in warnings:
        print(f"  [warn] {w}", file=sys.stderr)
    for e in errors:
        print(f"  [error] {e}", file=sys.stderr)
    task_count = len(re.findall(r"^### Task \d+", text, re.M))
    print(f"  tasks: {task_count}  checkboxes: {text.count('- [ ]')}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
