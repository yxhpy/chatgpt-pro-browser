---
name: chatgpt-pro-planner
description: Generate executable engineering plans (dev / test / refactor / bugfix) using ChatGPT Pro's reasoning, in the exact superpowers markdown format that Codex, Claude Code, and `executing-plans` / `subagent-driven-development` can consume directly. Use whenever the user wants to "做个开发计划/测试计划/重构计划/bug 修复计划", "用 Pro 拆任务", "plan this feature/refactor/bug with chatgpt pro", "generate an executable plan", "turn this spec into tasks", or any request to produce a plan/task-breakdown that downstream agent CLIs will execute. Pairs with the chatgpt-pro-browser harness. macOS only.
---

# ChatGPT Pro Planner

Use **ChatGPT Pro (GPT-5.5 Pro)** to produce engineering plans that downstream agents (Codex, Claude Code, Gemini CLI) execute. The plan comes out in the **superpowers markdown format** — the exact format `executing-plans` and `subagent-driven-development` parse — so the handoff is seamless.

## Dependency contract (read this before editing)

This skill **does NOT call Pro directly** and **does NOT import the browser harness**. The two skills are cleanly separated:

- **chatgpt-pro-browser** = the SOLE entry to ChatGPT Pro. Owns browser lifecycle, cookie decryption, Cloudflare, Pro verification, downgrade guard, paste-mode input, the resume loop, daemon reuse. It exposes `ask.py` (and the other atomic CLIs) as its supported interface.
- **chatgpt-pro-planner** (this skill) = pure planning knowledge only. It builds the prompt from its templates + `output-contract.md`, then hands the assembled text to `ask.py` via **subprocess** and treats the reply as opaque. It knows nothing about `ChatGPTSession`, paste mode, or how Pro is reached. The single point of contact is `_ask_via_browser_skill()` calling `skills/chatgpt-pro-browser/scripts/ask.py`.

This means: editing a planner template never risks breaking the browser layer, and vice versa. Process-isolated, no shared Python state.

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
2. **Gather context**: the goal (from the request) + optionally files (specs, source, README). If the user references files, they're passed to `ask.py --file` so Pro reads real content, not just the prompt.
3. **Load the type template** from `references/<type>-template.md` and the format spec from `references/output-contract.md` (both read fresh from disk every run — edits take effect immediately).
4. **Build the prompt**: the template's role/instructions prefix + `<OUTPUT_CONTRACT>` (the full output-contract.md content) + the user's goal + context summary.
5. **Send to Pro via the browser skill**: `plan.py` calls `skills/chatgpt-pro-browser/scripts/ask.py` as a **subprocess** with the assembled prompt. The browser skill handles everything Pro-related (browser, Cloudflare, Pro check, downgrade guard, paste input, resume loop, heartbeat). The planner just receives the reply text. The role instructions are embedded in the prompt prefix (Pro follows embedded role instructions well).
6. **Refine (multi-round)**: a second `ask.py` call with the type template's "Refinement cue". Pro self-reviews against the output contract and returns a corrected plan. This catches placeholders and type inconsistencies that slip into round 1.
7. **Save** the final plan to `docs/superpowers/plans/YYYY-MM-DD-<feature>-<type>.md` (normalize `* [ ]` → `- [ ]` on write).
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

Flags: `--out <path>` (default `docs/superpowers/plans/...`), `--no-refine` (skip round 2), `--headless`, `--timeout 600`.

**Templates are read live, not cached.** `plan.py` re-reads `references/<type>-template.md` and `references/output-contract.md` from disk on every invocation (`_read_ref()` opens the file fresh). So if you edit a template to tweak the prompt or output rules, the next `plan.py` call picks it up immediately — no reinstall, no restart. This applies to the installed codex plugin copy too (it reads from its own `references/`).

## Programmatic usage

The planner is a pure prompt-builder + a thin subprocess wrapper. It never
imports the browser harness. To drive it programmatically:

```python
import asyncio, sys
REPO = "<plugin root>"  # .../plugins/chatgpt-pro-browser
sys.path.insert(0, f"{REPO}/skills/chatgpt-pro-planner/scripts")
from plan import build_prompt, build_refinement_cue, save_plan, generate

# Option A — full pipeline (calls the browser skill's ask.py under the hood):
asyncio.run(generate("dev", "my goal", context_files=["README.md"]))

# Option B — just build the prompt (no Pro call; send it however you like):
prompt = build_prompt("dev", "my goal", context_files=["README.md"])
cue = build_refinement_cue("dev")
# hand `prompt` to chatgpt-pro-browser/scripts/ask.py yourself
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
