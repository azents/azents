---
name: stacked-prs
description: "Manage stacked PRs: rebase, merge, and retarget sequential PR branches. Use when: (1) the user asks to merge a stacked PR or stack, (2) later stack branches must be rebased after an earlier branch changes, (3) the user asks to inspect stacked PR status."
---

# Stacked PR Management

## What is a stacked PR?

A stacked PR series is a branch chain where each PR uses the previous branch as its base.

```text
main ← branch-A ← branch-B ← branch-C
PR#1: A → main   PR#2: B → A   PR#3: C → B
```

Merge from the front of the stack only. If an earlier branch changes, rebase every later branch in order.

## Workflow

### 1. Rebase following branches after an earlier branch changes

After adding or editing commits on an earlier branch, rebase each following branch sequentially.

```bash
# Record the old tip SHA of branch-A before changing it.
OLD_A_TIP=$(git rev-parse branch-A)

# After committing changes to branch-A...

# Rebase branch-B onto the new branch-A.
git rebase --onto branch-A $OLD_A_TIP branch-B

# Rebase branch-C onto the new branch-B. Record OLD_B_TIP beforehand too.
git rebase --onto branch-B $OLD_B_TIP branch-C
```

**Key rule:** when commit SHAs change because of squash merge or history rewrite, use the exact old tip SHA with `--onto`. A plain `git rebase branch-A` can create conflicts or duplicate/drop changes.

### 2. Merge one PR from the stack

Use this flow for the front PR in the stack:

1. **Retarget the next PR base to `main` before merging.** If `--delete-branch` deletes the current base branch, GitHub can close the dependent PR and make it impossible to reopen. Retargeting before merge prevents that.

   ```bash
   # Use the API directly if gh pr edit fails because of classic Projects errors.
   gh api repos/{owner}/{repo}/pulls/{next_pr_number} -X PATCH -f base=main
   ```

2. **Merge with squash and delete the branch.**

   ```bash
   gh pr merge {pr_number} --squash --delete-branch
   ```

3. **Cherry-pick following branch commits onto `main`.**

   After squash merge, `git rebase --onto` can treat identical changes as already applied and drop commits. Use cherry-pick instead.

   ```bash
   git fetch origin main
   # Record the unique commit SHAs from the following branch before resetting.
   git checkout next-branch
   git reset --hard origin/main
   git cherry-pick {commit1} {commit2} ...
   ```

   Verify before pushing:

   ```bash
   git log --oneline origin/main..next-branch
   git diff --stat origin/main..next-branch
   git push origin next-branch --force-with-lease
   ```

4. Repeat for the next PR.

### 3. Batch merge through a target PR

When the user asks to merge every PR up to `#N`, run preflight checks first.

#### Preflight checks

1. **Conflict check:** ensure every target PR has no merge conflicts. Resolve by rebase when needed.
2. **Commit consistency:** ensure the last branch includes all earlier changes.

   ```bash
   git log --oneline branch-B..branch-C
   git merge-base --is-ancestor branch-B branch-C && echo "OK"
   ```

3. **CI check:** wait until every target PR has passing CI before starting the merge sequence.

   ```bash
   gh pr checks {pr_number}
   ```

Also confirm approval, mergeability, zero unresolved review threads, and successful CI for every target PR.

After batch merging starts, retargeting, resetting, cherry-picking, and force-with-lease pushes may create new pending check runs. Do not wait for those newly created pending checks if the same changes already passed preflight CI. Verify the cherry-pick result with `git log` and `git diff --stat`, then continue. If you resolve cherry-pick conflicts manually, verify the resolved result before pushing.

#### Sequential merge loop

```text
for each PR in stack, from front to back:
  1. Retarget the next PR base to main, unless this is the last PR.
  2. Run gh pr merge --squash --delete-branch.
  3. Fetch origin/main.
  4. Reset the following branch to origin/main and cherry-pick its unique commits.
  5. Verify with git log and git diff --stat.
  6. Push with --force-with-lease.
  7. Continue without waiting for newly created pending CI checks.
```

### 4. When a PR cannot be reopened

If GitHub cannot reopen a PR because its base branch was deleted, create a new PR:

```bash
gh pr create --base main --head {branch} --title "..." --body "..." --reviewer {reviewer}
```

## Safety notes

- **Merge order:** always merge from front to back. Do not merge later PRs first.
- **Force push:** always use `--force-with-lease`; never use `--force`.
- **Working tree:** ensure the working tree is clean before rebasing. Stash if needed.
- **Approval:** do not merge without required approval.
- **Squash merge old tip:** after squash merge, original commits are replaced by one commit. Use the original pre-squash tip SHA when rebasing later branches.
