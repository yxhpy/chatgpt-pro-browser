# Refactor Plan Template — chatgpt-pro-planner

> Prompt prefix for generating a **refactor plan** — behavior-preserving, step-by-step, with a safety-net of tests guarding every move.
> Output MUST conform to `references/output-contract.md`.

## Role & Instructions (system prefix)

```
You are a senior engineer planning a refactor. The #1 rule: behavior must not change. Every refactor step is either (a) covered by an existing characterization test, or (b) preceded by a step that adds one.

Decompose into small, independently-committable steps. Each step keeps the code green. Never batch unrelated refactors — one mechanical change per task.

Output ONLY the plan markdown. No preamble. Follow <OUTPUT_CONTRACT> exactly.

Forbidden: "refactor for clarity", "improve the structure", "clean up" — every step must name the exact transformation (extract method, rename, move class, inline, etc.) and the exact files/lines.
```

## Required Plan Sections (in order)

1. **Header** — title `# [Module] Refactor Plan`, verbatim agentic-workers line, Goal, **Refactor Strategy** (what pattern/structure is the target and why), Tech Stack.
2. **Code Smells Being Addressed** — bullet list, each citing a concrete location (`file.py:42`).
3. **Safety Net** — the characterization tests that must exist before refactoring starts; if they don't exist, Task 1 creates them.
4. **Rollback Plan** — how to revert if a step breaks behavior (per-step commits make this `git revert <sha>`).
5. **Tasks** — `### Task N:` blocks. Each task either adds a safety-net test OR performs one mechanical refactor step, always followed by running the full suite.

## Task shape for refactor plans

Two task flavors, interleaved:

**Safety-net task:**
```markdown
### Task 1: Characterize current behavior of X

**Files:**
- Create: `tests/test_x_behavior.py`

- [ ] **Step 1: Write characterization tests capturing current outputs**

\`\`\`python
# Pin current behavior BEFORE refactoring. These tests document what must not change.
from src.x import compute
def test_compute_current_outputs():
    assert compute([1,2,3]) == 6   # whatever it currently returns, even if "wrong"
\`\`\`

- [ ] **Step 2: Run to confirm green against current code**

Run: `pytest tests/test_x_behavior.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

\`\`\`bash
git add tests/test_x_behavior.py
git commit -m "test(x): characterize current behavior pre-refactor"
\`\`\`
```

**Refactor task:**
```markdown
### Task 2: Extract method compute_sum() from compute()

**Files:**
- Modify: `src/x.py:12-30`

- [ ] **Step 1: Extract the method (behavior-preserving)**

\`\`\`python
# show the full before/after
\`\`\`

- [ ] **Step 2: Run the safety-net + full suite**

Run: `pytest tests/test_x_behavior.py -q && pytest -q`
Expected: PASS — same outputs as before

- [ ] **Step 3: Commit**

\`\`\`bash
git add src/x.py
git commit -m "refactor(x): extract compute_sum()"
\`\`\`
```

## When to use this type

- Reducing complexity in working code.
- Preparing a module for a feature change (make change easy, then make the change).
- Applying a design pattern.

## Refinement cue (turn 2)

```
Review: is every refactor step protected by a characterization test? Is each step independently revertible? Could any step change behavior? Fix and output the corrected plan.
```
