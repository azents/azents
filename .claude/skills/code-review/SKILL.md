---
name: code-review
description: "Perform code review. Use for: (1) '/code-review' to review the current branch changes, (2) '/code-review PR #123' to review a specific PR, (3) '/code-review staged' to review staged changes, (4) requests such as 'review this code' or 'please review'."
---

# Code Review (/code-review)

Review changed code and report issues and improvements grouped by severity.

**Unless instructed otherwise, always apply review findings to the code.** Fix Critical and Warning findings immediately. Apply Suggestion and Consistency findings when they are reasonable.

## Workflow

### 1. Determine the review target

Determine the diff target from the argument:

| Argument | Target |
| --- | --- |
| (none) | Full current branch diff against the parent branch |
| `staged` | Staged changes (`git diff --cached`) |
| `last` | Last commit (`git diff HEAD~1`) |
| `PR #N` | Diff for that PR (`gh pr diff N`) |
| `<file ...>` | Only the specified files, diffed against the parent branch |

Determine the parent branch in this order:

1. Use `gh pr view --json baseRefName` to identify the PR base branch.
2. If there is no PR, infer the branch point from sources such as `git log --oneline --merges -1`.
3. If still unclear, use `main`.

### 2. Collect context

Before reviewing, collect the following:

**a. Project rules**

- Read every applicable `CLAUDE.md`, `AGENTS.md`, and `.claude/CLAUDE.md` while walking from the changed file path up to the project root.
- Example: when `python/apps/azents/src/handler.py` changes, read:
  1. `python/apps/azents/CLAUDE.md` (or `AGENTS.md`, `.claude/CLAUDE.md`)
  2. `python/apps/CLAUDE.md`
  3. `python/CLAUDE.md`
  4. Root `CLAUDE.md`
- Lower-level rules override higher-level rules, but include every applicable level in the review criteria.

**b. Existing patterns for consistency checks**

- Identify the app that owns the changed file, for example `python/apps/azents/` or `typescript/apps/azents-web/`.
- Search that app for existing implementations similar to the change:
  - New API endpoint → existing endpoint patterns
  - New service → existing service class patterns
  - New repository → existing repository patterns
  - New test → existing test patterns
  - And similar cases
- Identify naming conventions, import style, error handling, and directory structure.

### 3. Run the review

Use a code-review subagent when the runtime supports it. Pass this content when spawning the subagent:

```
Agent(subagent_type="code-review"):
  - Provide the diff.
  - Provide project rules.
  - Provide reference file paths for existing patterns.
  - Include the review criteria and output format below in the prompt.
  - Grounding rules: only report findings grounded in actual code; do not speculate.
  - Dig deeper: check second-order failures, edge cases, and rollback risk.
```

If no specialized review profile is available, use a general-purpose subagent and pass the same constraints directly in the prompt.

### 4. Review criteria

Review in priority order:

| Priority | Category | What to check |
| --- | --- | --- |
| 1 | **Correctness** | Logic errors, off-by-one errors, missing null/undefined handling, type mismatches |
| 2 | **Security** | Injection, auth bypasses, data exposure, OWASP Top 10 |
| 3 | **Data integrity** | Race conditions, transaction boundaries, migration safety |
| 4 | **Error handling** | Failure modes, recovery paths, error-message quality |
| 5 | **Performance** | N+1 queries, unnecessary work, memory leaks |
| 6 | **Design** | Coupling, separation of responsibilities, testability |
| 7 | **Consistency** | Alignment with existing patterns in the same app |
| 8 | **Project rules** | Compliance with CLAUDE.md/AGENTS.md rules, such as comment and log language requirements |

**Do not review:**

- Formatting/style covered by linters
- Ungrounded personal preferences
- Issues already caught by the type checker or linter
- Pre-existing problems in unchanged code

### 5. Output format

Group findings by severity. Omit severities with no findings.

```
## Code Review Result

Review target: `feat/my-feature` vs `main` (15 files changed)

### Critical
- **file.py:42** — External API call occurs inside the DB transaction before commit
  This risks data inconsistency. Move the API call after the transaction commits.

### Warning
- **service.ts:15** — The catch block swallows the error
  The root cause will be hard to trace during debugging. Add `logger.error`.

### Suggestion
- **handler.py:88** — The same query runs repeatedly inside a loop
  This is an N+1 query pattern. Use prefetching or a batch query.

### Consistency
- **new_service.py:1** — Existing services inherit from `BaseService` (reference: `user_service.py`)
  Use the same pattern for the new service.
```

If there are no findings:

```
## Code Review Result

Review target: `feat/my-feature` vs `main` (3 files changed)

No issues found.
```
