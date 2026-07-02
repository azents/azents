---
name: ship-pr
description: "Run the PR shipping flow. Use for: (1) '/ship-pr', (2) requests such as 'create a PR and monitor it'. PR creation itself is delegated to /create-pr."
---

# Ship PR (/ship-pr)

Check that the current branch is ready for review, then create the PR through `/create-pr`. This skill owns the quality and spec gates; the actual PR creation procedure is delegated to `/create-pr`.

## Workflow

### 1. Code review (required)

Before creating the PR, always run the `/code-review` skill for self-review. Do not skip it.

Run review and fixes only once. After `/code-review` → apply required fixes → commit, do not start another review loop within the same `/ship-pr` execution. Continue to the next step.

- If Critical/Warning findings are found → fix them, commit, then continue.
- If there are only Suggestion/Consistency findings, or no findings → continue immediately.

### 2. Apply required fixes

If `/code-review` identifies required code or documentation fixes, apply them on the same branch.

This step runs only once. Do not call `/code-review` again to look for new Critical/Warning findings after the fix. If additional review is needed, handle it through the normal PR review process after PR creation.

- If Critical/Warning findings are found → fix them, then continue.
- If there are only Suggestion/Consistency findings, or no findings → continue immediately.

### 3. Call `/create-pr`

Call `/create-pr` with the validation context. Because `/create-pr` only creates the PR, leave the following information in the conversation context so it can be included in the PR body when appropriate:

- Tests and quality checks that were run, plus results
- Whether the PR body should include `## Spec Impact`

Follow the `/create-pr` rules.

### 4. Report the result

- Created PR URL
- `/code-review` result
