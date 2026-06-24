---
title: Use `scripts/rebase-stacked-prs.sh` when rebasing stacked PR branches together so the process stops cleanly at the first conflict.
---

# Stacked PR Rebase Script

- ALWAYS use `scripts/rebase-stacked-prs.sh` when rebasing a stacked PR branch chain together.
- The branch arguments must be ordered from the front of the stack to the back: `branch1 branch2 branch3`.
- Let the script stop on the first conflict; do not continue downstream branches after a conflicted rebase.
- Use `--push` only after confirming the intended history rewrite is acceptable for every listed branch.

## Bad

```bash
git switch branch-a
git rebase origin/main
git switch branch-b
git rebase branch-a
```

## Good

```bash
scripts/rebase-stacked-prs.sh branch-a branch-b branch-c
```

```bash
scripts/rebase-stacked-prs.sh --push branch-a branch-b branch-c
```
