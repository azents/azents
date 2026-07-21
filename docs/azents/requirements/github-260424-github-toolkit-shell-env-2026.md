---
title: "GitHubToolkit Shell Env Injection Feature Historical Requirements Reconstruction"
created: 2026-04-24
implemented: 2026-04-24
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: github-260424
historical_reconstruction: true
migration_source: "docs/azents/design/github-toolkit-shell-env-2026-04-24.md"
---

# GitHubToolkit Shell Env Injection Feature Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `github-260424`
- Source: `docs/azents/design/github-260424-github-toolkit-shell-env-2026.md`
- Historical source date basis: `2026-04-24`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

A path to inject arbitrary env into sandbox shell with `EnvVarToolkit` has shipped. Based on this, add shell env injection to existing `GitHubToolkit` so **agent can immediately execute automation such as `git push`, `gh pr create` from shell**.

Core: **not a separate toolkit type or token source addition.** Expose the tokens issued/stored by the 3 auth modes already supported by `GitHubToolkit` (`per_user_pat`, `github_app`, `github_app_platform`) to sandbox shell through `Toolkit.expose_env()`.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Workspace manager:
1. Edit existing GitHubToolkit in `/w/{handle}/toolkits`
2. Turn ON "Expose shell env" toggle + acknowledge warning checkbox
3. Save

Agent session (LLM):
```
$ gh repo clone owner/repo target/
$ cd target && echo "fix" > README.md
$ git add README.md && git commit -m "docs"
$ git push origin HEAD:fix-branch
$ gh pr create --title "Docs fix" --body "..."
```
All commands above run **with automatic authentication**. Token is freshly supplied by GitHubToolkit on every resolve.

## Supporting Scenarios

Workspace manager:
1. Edit existing GitHubToolkit in `/w/{handle}/toolkits`
2. Turn ON "Expose shell env" toggle + acknowledge warning checkbox
3. Save

Agent session (LLM):
```
$ gh repo clone owner/repo target/
$ cd target && echo "fix" > README.md
$ git add README.md && git commit -m "docs"
$ git push origin HEAD:fix-branch
$ gh pr create --title "Docs fix" --body "..."
```
All commands above run **with automatic authentication**. Token is freshly supplied by GitHubToolkit on every resolve.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
