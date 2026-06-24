---
title: In codingbot or bare-cache worktrees, refresh origin/main with an explicit refspec before rebasing onto main — `git fetch origin main` alone may leave origin/main stale.
---

# Worktree Rebase Onto Main

Bare-cache worktrees can fetch `main` without updating the local `origin/main` remote-tracking ref.

- ALWAYS run `git fetch origin main:refs/remotes/origin/main` before rebasing a worktree branch onto main.
- AVOID relying on `git fetch origin main` when the next step uses `origin/main`.
- If you need to inspect the refreshed base, run `git log --oneline -1 origin/main` after the explicit fetch.

## Bad

```bash
git fetch origin main
git rebase origin/main
```

## Good

```bash
git fetch origin main:refs/remotes/origin/main
git rebase origin/main
```
