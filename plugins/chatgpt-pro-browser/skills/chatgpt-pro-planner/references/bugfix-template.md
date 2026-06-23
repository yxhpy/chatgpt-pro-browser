# Bugfix Plan Template — chatgpt-pro-planner

> Prompt prefix for generating a **bug-fix plan** — reproduce → root-cause → fix → regression-guard, each as discrete verifiable steps.
> Output MUST conform to `references/output-contract.md`.

## Role & Instructions (system prefix)

```
You are a senior engineer debugging and fixing a bug. Think in four phases, each with its own task(s):
  1. REPRODUCE — write a failing test that triggers the bug (the bug exists = the test fails).
  2. ROOT CAUSE — explain precisely why it happens, citing code locations.
  3. FIX — minimal change that makes the repro test pass without breaking others.
  4. REGRESSION GUARD — confirm the fix and add a guard test so it never returns.

Never propose a fix without a reproducing test. Never fix the symptom; fix the cause. Output ONLY the plan markdown. No preamble. Follow <OUTPUT_CONTRACT> exactly.
```

## Required Plan Sections (in order)

1. **Header** — title `# Bugfix: [one-line description]`, verbatim agentic-workers line, Goal, **Hypothesis** (the suspected cause, to be confirmed), Tech Stack.
2. **Reproduction** — exact steps/command/inputs that trigger the bug, and the observed-vs-expected output.
3. **Root Cause Analysis** — where in the code the defect lives, why. (This section summarizes; Task 2 nails it down with the fix.)
4. **Tasks** — `### Task N:` blocks following the 4-phase structure.

## Task shape for bugfix plans

```markdown
### Task 1: Reproduce the bug with a failing test

**Files:**
- Create: `tests/test_bug_<id>.py`

- [ ] **Step 1: Write the reproducing test**

\`\`\`python
def test_bug_<id>_repro():
    # This test SHOULD fail right now — it captures the bug.
    result = func(buggy_input)
    assert result == expected_correct   # currently returns wrong value
\`\`\`

- [ ] **Step 2: Run to confirm it fails (the bug is reproduced)**

Run: `pytest tests/test_bug_<id>.py -v`
Expected: FAIL — result == [actual wrong value], not [expected]

- [ ] **Step 3: Commit the failing test**

\`\`\`bash
git add tests/test_bug_<id>.py
git commit -m "test: reproduce bug #<id>"
\`\`\`

### Task 2: Fix the root cause

**Files:**
- Modify: `src/module.py:NN`  (the exact defect location)

- [ ] **Step 1: Apply the minimal fix**

\`\`\`python
# show before/after of the changed lines
\`\`\`

- [ ] **Step 2: Run the repro test — it should now pass**

Run: `pytest tests/test_bug_<id>.py -v`
Expected: PASS

- [ ] **Step 3: Run the full suite to catch regressions**

Run: `pytest -q`
Expected: PASS (no new failures)

- [ ] **Step 4: Commit**

\`\`\`bash
git add src/module.py
git commit -m "fix(module): <root cause> (bug #<id>)"
\`\`\`
```

## When to use this type

- A specific bug report (with repro or symptom).
- Intermittent failure you've now pinned down.
- Regression after a change.

## Refinement cue (turn 2)

```
Review: does the reproducing test actually fail against the current (buggy) code? Does the fix target the cause, not the symptom? Could the fix break any other case? Fix and output the corrected plan.
```
