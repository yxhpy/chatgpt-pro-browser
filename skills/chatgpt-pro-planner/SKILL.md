---
name: chatgpt-pro-planner
description: Generate executable engineering plans (dev / test / refactor / bugfix) using ChatGPT Pro's reasoning, in the exact superpowers markdown format that Codex, Claude Code, and `executing-plans` / `subagent-driven-development` can consume directly. Use whenever the user wants to "做个开发计划/测试计划/重构计划/bug 修复计划", "用 Pro 拆任务", "plan this feature/refactor/bug with chatgpt pro", "generate an executable plan", "turn this spec into tasks", or any request to produce a plan/task-breakdown that downstream agent CLIs will execute. Pairs with the chatgpt-pro-browser harness. macOS only.
---

# ChatGPT Pro Planner

Use **ChatGPT Pro (GPT-5.5 Pro)** to produce engineering plans that downstream agents (Codex, Claude Code, Gemini CLI) execute. The plan comes out in the **superpowers markdown format** — the exact format `executing-plans` and `subagent-driven-development` parse — so the handoff is seamless.

This skill **depends on `chatgpt-pro-browser`** (the sibling skill in this plugin). It reuses that harness to call Pro.

## When to use

Trigger on any planning request:
- "用我的 ChatGPT Pro 做个开发计划" / "用 Pro 拆这个需求" / "plan a feature with chatgpt pro"
- "为这个模块生成测试计划" / "test plan for X"
- "重构计划" / "refactor plan"
- "修这个 bug，先出个修复计划" / "bugfix plan"
- "turn this spec/issue into executable tasks"

The user's request maps to one of four plan types. If ambiguous, ask which type (dev / test / refactor / bugfix).

## How it works

1. **Determine plan type** from the request: `dev`, `test`, `refactor`, or `bugfix`.
2. **Gather context**: the goal (from the request) + optionally files (specs, source, README). If the user references files, upload them so Pro reads real content, not just the prompt.
3. **Load the type template** from `references/<type>-template.md` and the format spec from `references/output-contract.md`.
4. **Build the prompt**: the template's role/instructions prefix + `<OUTPUT_CONTRACT>` (the full output-contract.md content) + the user's goal + context summary.
5. **Call Pro** via `lib/harness.py`'s `ChatGPTSession.ask()`. The harness has no `system` role, so the role instructions are prepended to the user prompt (proven effective — Pro follows embedded role instructions well).
6. **Refine (multi-round)**: in the SAME chat, send the type template's "Refinement cue" (turn 2). Pro self-reviews against the output contract and returns a corrected plan. This catches placeholders and type inconsistencies that slip into round 1.
7. **Save** the final plan to `docs/superpowers/plans/YYYY-MM-DD-<feature>-<type>.md`.
8. **Validate** with `scripts/validate_plan.py` — a hard format check. If it fails, run another refinement round.
9. **Hand off**: tell the user the two execution paths (subagent-driven-development / executing-plans), exactly like `writing-plans` does.

## The four plan types

| Type | When | Template | Key sections |
|---|---|---|---|
| `dev` | New feature / capability | `references/dev-template.md` | File Structure + TDD tasks |
| `test` | Build out test suite / harden | `references/test-template.md` | Strategy + Coverage Targets + Acceptance + test tasks |
| `refactor` | Improve structure, keep behavior | `references/refactor-template.md` | Code Smells + Safety Net + Rollback + refactor tasks |
| `bugfix` | Fix a specific bug | `references/bugfix-template.md` | Reproduction + Root Cause + 4-phase tasks |

Read `references/<type>-template.md` before generating that type — it contains the exact role prefix and section order Pro must follow.

## Output contract (non-negotiable)

Before generating ANY plan, read `references/output-contract.md`. It defines the superpowers markdown format that downstream agents parse:
- Mandatory header with the verbatim `> **For agentic workers:**` line.
- `### Task N:` headings, each with a `**Files:**` block.
- `- [ ]` checkbox steps (one action each, 2-5 min).
- `Run:` + `Expected:` on every verification step.
- **No placeholders** (TBD/TODO/"add error handling"/etc. are plan failures).

If Pro's output violates the contract, the plan is broken — run another refinement round.

## CLI usage

```bash
# Quick: one-shot generate (plan.py handles prompt-build + refine + save + validate)
python3 skills/chatgpt-pro-planner/scripts/plan.py dev \
    "Add streaming support to lib/harness.py" \
    --context lib/harness.py --context README.md

python3 skills/chatgpt-pro-planner/scripts/plan.py test \
    "Test the cookie-decryption path" \
    --context lib/harness.py

python3 skills/chatgpt-pro-planner/scripts/plan.py refactor \
    "Extract cookie logic out of harness.py into cookies.py"

python3 skills/chatgpt-pro-planner/scripts/plan.py bugfix \
    "Upload timeout when send button stays disabled" \
    --context lib/harness.py
```

Flags: `--out <path>` (default `docs/superpowers/plans/...`), `--no-refine` (skip round 2), `--headless`, `--timeout 300`.

## Programmatic usage

```python
import asyncio, sys, os
REPO = "<repo root>"
sys.path.insert(0, os.path.join(REPO, "lib"))
sys.path.insert(0, os.path.join(REPO, "skills", "chatgpt-pro-planner", "scripts"))
from harness import ChatGPTSession
from plan import build_prompt, save_plan   # helpers in scripts/plan.py

async def main():
    async with ChatGPTSession(headless=False) as s:
        await s.ensure_pro()
        await s.new_chat()
        prompt = build_prompt("dev", "my goal", context_files=["lib/harness.py"],
                              repo_root=REPO)
        r = await s.ask(prompt, timeout=300)
        # refine
        r2 = await s.ask(build_refinement_cue("dev", repo_root=REPO), timeout=300)
        path = save_plan(r2.text, "my-goal", "dev", repo_root=REPO)
        print(f"saved → {path}")

asyncio.run(main())
```

## Why Pro for planning

GPT-5.5 Pro's deep reasoning is strong at: decomposing goals into atomic steps, spotting type/name inconsistencies across tasks, catching missing spec coverage, and self-reviewing against a format spec. The multi-round refinement (round 2 = "review against contract, fix, return corrected") exploits this — round-1 drafts with placeholders get fixed in round 2.

## Prerequisites

Same as `chatgpt-pro-browser` (this skill uses its harness): macOS, real Chrome logged into chatgpt.com (Pro), Python deps. Run `scripts/prereq_check.sh` from the sibling skill.

## Handoff (after the plan is saved)

Offer the two execution paths, identical to `writing-plans`:

> Plan saved to `docs/superpowers/plans/<file>.md`. Two ways to execute:
> 1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task via `superpowers:subagent-driven-development`.
> 2. **Inline** — execute task-by-task in this session via `superpowers:executing-plans`.

For Codex/Claude Code without superpowers: hand them the plan file path and say "execute this plan task by task" — the format is plain markdown they can follow.
