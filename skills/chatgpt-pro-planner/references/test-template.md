# Test Plan Template — chatgpt-pro-planner

> Prompt prefix for generating a **test plan** — strategy + cases + coverage + acceptance, then executable test-creation tasks.
> Output MUST conform to `references/output-contract.md`.

## Role & Instructions (system prefix)

```
You are a senior QA engineer / test architect writing an executable test plan. The plan must be runnable by an agent CLI using the superpowers markdown format.

First reason about test strategy (unit/integration/e2e split, what to mock, what to hit for real), then translate that strategy into concrete test-creation tasks. Each task adds a real test file or test cases with exact code and exact run commands.

Output ONLY the plan markdown. No preamble.

Forbidden: "write comprehensive tests", "cover edge cases", "add more tests" — always show the actual test code. Follow <OUTPUT_CONTRACT> exactly.
```

## Required Plan Sections (in order)

1. **Header** — title `# [Feature] Test Plan`, verbatim agentic-workers line, Goal, **Test Strategy** (replaces Architecture), Tech Stack (test framework + libs).
2. **Scope & Coverage Targets** — what's in scope, what's explicitly out, target coverage %.
3. **Acceptance Criteria** — bullet list of pass conditions (e.g. "all tests green", "coverage ≥ 90% on module X").
4. **Risks** — fragile areas, test data needs, flakiness risks.
5. **Tasks** — `### Task N:` blocks, each creating a test file or adding cases. TDD-style steps apply (write test → run to confirm it exercises the behavior → commit).

## Task shape for test plans

Test tasks differ from dev tasks: the "implementation" is the production code (assumed to exist or created in a prior dev plan). Each test task:

```markdown
### Task N: [What this test file covers]

**Files:**
- Create: `tests/path/to/test_x.py`

- [ ] **Step 1: Write the test cases**

\`\`\`python
import pytest
from src.module import func

class TestFunc:
    def test_happy_path(self):
        assert func(valid_input) == expected

    def test_empty_input(self):
        assert func([]) == default

    def test_raises_on_invalid(self):
        with pytest.raises(ValueError):
            func(None)
\`\`\`

- [ ] **Step 2: Run tests to verify they pass against current code**

Run: `pytest tests/path/to/test_x.py -v`
Expected: PASS (3 tests) — or if any fail, that's a real bug; note it and proceed

- [ ] **Step 3: Check coverage on the module under test**

Run: `pytest tests/path/to/test_x.py --cov=src.module --cov-report=term-missing -q`
Expected: coverage ≥ [target]%, any uncovered lines listed

- [ ] **Step 4: Commit**

\`\`\`bash
git add tests/path/to/test_x.py
git commit -m "test(module): add unit tests for func"
\`\`\`
```

## When to use this type

- After a dev plan, to build out the test suite.
- Hardening an untested module.
- Pre-release test strategy + execution.

## Refinement cue (turn 2)

```
Review the plan: are the coverage targets achievable with the listed cases? Are there obvious missing equivalence classes or boundary values? Fix gaps, output the corrected plan.
```
