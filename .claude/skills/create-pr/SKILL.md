---
name: create-pr
description: "Create a GitHub PR from the current branch. Proactively use when: (1) '/create-pr', (2) requests such as 'create a PR', 'open a PR', 'submit a PR', (3) opening an already prepared branch as a PR. Focus only on PR creation; do not run code review or spec review."
---

# Create PR (/create-pr)

Create a GitHub PR from the current branch. This skill is responsible only for PR creation. When a shipping flow needs quality gates such as `/code-review` or `/spec-review`, `/ship-pr` calls this skill.

## Steps

### 1. Check status

- Check the current branch: `git branch --show-current`.
- Check whether an open PR already exists: `gh pr list --head "$(git branch --show-current)" --state open --json number,url`.
- If an open PR exists, do not create another PR; report the existing PR URL.
- Use `main` as the default base branch. If the branch clearly forked from another base, follow the upstream base or the user's instruction.
- If both `git log <base>..HEAD` and `git status --short` are empty, stop because there is nothing to open as a PR.

### 2. Prepare uncommitted changes

If `git status --short` is empty, skip this step. If there are changes, stage only related files and create one focused commit.

- Specify the file paths to include in the PR instead of using `git add -A` blindly.
- Ask before staging files that look like `.env`, credentials, large binaries, or temporary scratch files.
- If clearly unrelated changes are mixed in, ask whether to split the commit.
- Check recent commit style: `git log --oneline -5`.
- Use conventional commit style by default: `<type>(<scope>): <summary>`.
- If hooks fail, fix the cause and create a new commit.

### 3. Push

- If remote tracking is missing, use `git push -u origin <branch>`.
- Perform a normal push automatically when it is fast-forward safe.
- If the remote diverged and history rewrite is required, ask the user first.
- If the user's request explicitly implies history rewrite, such as amend, rebase, squash, or commit cleanup, `--force-with-lease` is allowed.
- Do not use `--force`.

### 4. Write the PR title

Follow recent commit/PR style, defaulting to conventional style.

Examples:

```text
fix(runtime): preserve tool-call observation status
chore(skills): remove stale project-specific skills
```

### 5. Write the PR body

Write the PR body to a file and pass it with `--body-file`. Do not put an inline heredoc directly into `gh pr create` arguments.

For Azents, write the PR title and body in English unless the user explicitly requests otherwise.

#### Summary principles

- Start the PR body with `## Summary`.
- The first sentence should immediately identify what the PR is.
- Do not start with background, motivation, or implementation history.
- Do not list files or narrate the diff. The Files changed tab already does that.
- Describe changes by behavior, feature, or policy.
- For simple PRs, use one sentence or one to three bullets.
- Split long `so ...` or `which ...` sentences into action and effect.

Bad:

```markdown
## Summary

This was needed because the existing flow had problems.

- Changed engine_adapter.py
- Changed model_factory.py
- Saves files to S3 so the parent agent can read them later
```

Good:

```markdown
## Summary

Restores SDK builtin tool routing for Azents agent runs.

- Routes builtin tool requests through provider-specific adapters.
- Preserves generated images as attachments instead of storing base64 data in event history.
- Stores generated files in S3. Parent agents can read them later.
```

#### Optional blocks

Add these blocks only for complex PRs. Put the block name on its own line, then explain in the following paragraph or bullets.

- `**Background**`: Explain why the change is needed, what user or operational problem it reduces, and what decision context matters. Do not use this for implementation history.
- `**What changed**`: Group by behavior, feature, or policy instead of listing files.
- `**Review focus**`: Call out risks, boundaries, and intentionally omitted work.
- `**Screenshots**`: Include only for UI/UX changes.
- `## Test Plan`: Include only when validation details help reviewers understand the PR.
- `## Spec Impact`: Include only when the spec impact is clear. If uncertain, omit it or ask the user briefly.

Example:

```markdown
## Summary

Restores shutdown recovery for interrupted Azents agent runs.

**Background**

A shutdown was recorded as a terminal failure, so interrupted runs could not be resumed.

**What changed**

- Preserves shutdown-interrupted runs as recovery candidates.
- Keeps explicit failures in a terminal state.

**Review focus**

- Confirm that shutdown paths and real failure paths remain separated.
```

### 6. Create the PR

Review the body file content, then create the PR.

```bash
gh pr create --base <base> --head <branch> --title "<title>" --body-file <body-file>
```

### 7. Report the result

- PR URL
- Whether a new commit was created
- Push mode: normal / upstream set / force-with-lease
- Validation that was run, or why validation was skipped
- Whether a `Spec Impact` section was included

## Safety guards

- If an existing PR is open, do not create a new PR.
- Do not commit suspicious secrets, credentials, or large binaries without user confirmation.
- Do not use destructive git commands.
