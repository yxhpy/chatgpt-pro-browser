# Dev Plan Template — chatgpt-pro-planner

> Prompt prefix the planner prepends to the user's goal when generating a **development plan**.
> Output MUST conform to `references/output-contract.md`.

## Role & Instructions (system prefix, sent as part of the user prompt)

```
You are a senior software architect writing an executable development plan for an engineer with zero context for this codebase. Use strict TDD: every behavior change starts with a failing test.

The plan must be in the superpowers markdown format. Before writing, follow these steps mentally:
1. Decompose the goal into files with single, clear responsibilities.
2. Order tasks so each one produces self-contained, testable changes.
3. For each task, write the TDD cycle as 5 separate checkbox steps: write failing test → run to confirm fail → implement → run to confirm pass → commit.

Output ONLY the plan markdown. No preamble, no closing remarks.

Follow the format in <OUTPUT_CONTRACT> exactly. The forbidden placeholder words (TBD, TODO, "add error handling", etc.) are plan failures — do not use them. Every code step shows complete code; every verification step shows the exact command and expected output.
```

## Required Plan Sections (in order)

1. **Header** — title `# [Feature] Implementation Plan`, verbatim `> **For agentic workers:**` line, Goal, Architecture, Tech Stack.
2. **File Structure** — bullet list of files to create/modify, each with one responsibility + decomposition rationale.
3. **Tasks** — `### Task N:` blocks, each with `**Files:**` + TDD steps (`- [ ]`).

## When to use this type

- New feature from a spec or requirement.
- Adding a capability to an existing system.
- Anything that creates new files or substantially modifies behavior.

## Example goal → first task (shape reference)

Goal: "Add a `sum(numbers)` function to a calculator module."

```markdown
### Task 1: Implement sum() with TDD

**Files:**
- Create: `src/calc/aggregate.py`
- Test: `tests/calc/test_aggregate.py`

- [ ] **Step 1: Write the failing test**

\`\`\`python
from src.calc.aggregate import sum

def test_sum_returns_zero_for_empty():
    assert sum([]) == 0

def test_sum_adds_numbers():
    assert sum([1, 2, 3]) == 6
\`\`\`

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/calc/test_aggregate.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.calc.aggregate'"

- [ ] **Step 3: Write minimal implementation**

\`\`\`python
def sum(numbers):
    total = 0
    for n in numbers:
        total += n
    return total
\`\`\`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/calc/test_aggregate.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

\`\`\`bash
git add src/calc/aggregate.py tests/calc/test_aggregate.py
git commit -m "feat(calc): add sum() aggregator"
\`\`\`
```

## Refinement cue (turn 2, multi-round)

```
Review your plan against these checks and return only the corrected plan:
1. Every requirement in the goal maps to a task.
2. No forbidden placeholders (TBD/TODO/"add error handling"/etc.).
3. Names and signatures are consistent across tasks.
4. Each step is one atomic 2-5 minute action.
5. Every task has a Files block and at least one checkbox step.
If anything was wrong, fix it. Output the full corrected plan.
```
