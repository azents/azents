---
name: review-pull-request
description: Review a GitHub pull request against repository conventions, tests, and concrete correctness risks.
---

# Review Pull Request

Use the GitHub Toolkit that owns this Skill to inspect the pull request, changed files, checks, and review threads.

1. Read repository instructions and the pull request description.
2. Inspect the complete diff and relevant surrounding code.
3. Prioritize correctness, security, data loss, concurrency, and compatibility risks.
4. Verify tests cover the changed behavior and identify missing cases.
5. Avoid speculative style comments that are not tied to repository conventions.
6. Report findings with file and line references, ordered by severity.

The ToolkitConfig slug can differ from the `github` content namespace. Use the concrete GitHub tool prefix shown in the current toolkit prompt.
