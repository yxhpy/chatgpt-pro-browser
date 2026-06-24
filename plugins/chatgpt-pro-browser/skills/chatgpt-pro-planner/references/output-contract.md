# Output Contract — Superpowers Markdown Plan Format

> **The planner MUST produce plans in this exact format.** This is the load-bearing contract: plans that deviate break `executing-plans` and `subagent-driven-development`, which parse markdown headings, `### Task N:` sections, and `- [ ]` checkboxes.

## Mandatory Header

Every plan begins with this header (replace `[...]` with real content):

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

For non-dev plan types, adapt the title:
- Test plan → `# [Feature Name] Test Plan`
- Refactor plan → `# [Feature Name] Refactor Plan`
- Bugfix plan → `# Bugfix: [short description]`

Keep the `> **For agentic workers:**` line verbatim in ALL plan types — it tells downstream agents which skill to invoke.

## File Structure Section (dev/refactor only)

Immediately after the header, map the files:

```markdown
## File Structure

- `src/foo.py` — [one responsibility]
- `src/bar.py` — [one responsibility]
- `tests/test_foo.py` — [tests for foo]

Decomposition rationale: [why these boundaries]
```

Test plans and bugfix plans may omit this section if no new file layout is needed.

## Task Structure (the core)

Each task is an H3 heading followed by a **Files** block, then numbered **Steps**. Each step is a single checkbox (`- [ ]`) representing one 2-5 minute action.

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## Step Granularity Rules

- **Each step is ONE action (2-5 minutes).** "Write the failing test", "run it to confirm it fails", "implement", "run to confirm pass", "commit" are FIVE separate steps, never one.
- **Every code-changing step shows complete code** in a fenced block — never a description like "add the validation logic".
- **Every verification step has `Run:` (exact command) + `Expected:` (exact output).**
- **Checkbox syntax is exactly `- [ ]`** — NOT `* [ ]`, NOT `- [x]`, not `* [x]`. Downstream agents (`executing-plans`) parse the literal `- [ ]` sequence; the asterisk form `* [ ]` is valid markdown but breaks their parser. Use a hyphen-minus, always.
- **All list items use `-` (hyphen), not `*` (asterisk)** — for Files blocks AND checkboxes. Asterisk bullets fail downstream tooling.

## No Placeholders (Plan Failures)

These are forbidden — if the planner emits any of them, the plan is broken and must be regenerated:

- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Write tests for the above" (without actual test code)
- "Similar to Task N" (repeat the code — agents may read tasks out of order)
- Steps that describe *what* to do without showing *how* (no code block = invalid)
- References to types/functions/methods not defined in any earlier task

## Type Consistency

A function called `clearLayers()` in Task 3 but `clearFullLayers()` in Task 7 is a bug. The planner must re-check that names, signatures, and property names match across all tasks before emitting the final plan.

## Plan-Type-Specific Sections

Each `references/<type>-template.md` adds sections specific to its plan type (e.g. a bugfix plan adds "Reproduction" and "Root Cause"; a test plan adds "Coverage Targets" and "Acceptance Criteria"). Those sections live ABOVE the tasks, never replacing the task structure.

## Self-Review Checklist (planner runs before finalizing)

Before returning the plan, verify:
1. **Spec coverage:** every requirement in the user's goal maps to at least one task. List any gaps.
2. **Placeholder scan:** grep the plan for the forbidden patterns above. Fix any found.
3. **Type consistency:** names/signatures match across tasks.
4. **Every step is atomic** (2-5 min, one action).
5. **Every `### Task N:` has a `**Files:**` block** and at least one `- [ ]` step.

If any check fails, fix inline and re-verify — do not hand off a broken plan.
