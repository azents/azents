---
title: "Transaction Ownership Phase 1: Session Title and ChatGPT OAuth"
created: 2026-09-08
tags: [backend, architecture, database]
---

# Phase Execution Plan

- Phase: 1, Session title and ChatGPT OAuth persistence.
- Branch/base: `refactor/title-repository-transactions-260908` → `main`.
- PR boundary: one reviewable title-generation and ChatGPT OAuth transaction
  ownership correction with operation repositories and deterministic regression
  tests.
- Inputs: requester transaction rules and implementation instruction;
  [transaction-260908/DESIGN](../design/transaction-260908-repository-ownership.md).
- Deliverables: title OAuth freshness, model generation, and External Channel
  title projection execute without an active caller transaction; title and
  refresh persistence return completed database results.
- Non-goals: claiming complete repository migration, changing OAuth concurrency
  policy, adding distributed locks, changing delivery or authorization policy.
- Mechanisms: M1, M2, M3, M4, M5.
- Authorities: `transaction-260908/REQ-1` through `REQ-5`;
  `transaction-260908/ADR-D1` through `ADR-D3`.
- Design delta: None.

| Workstream | Owner | Owned paths | Dependencies / output | Validation |
| --- | --- | --- | --- | --- |
| Title and ChatGPT freshness persistence | `/root/impl-title` | `services/session_title.py`, `services/chatgpt_oauth/runtime.py`, related tests, new title/integration operation repositories, required helper callers | Existing Agent/Session/integration repositories; completed title reads, conditional write, and refresh persistence without changing existing OAuth concurrency policy | OAuth/model/projection boundary, generation guard, title and refresh tests |
| Integration and documents | `/root` | Snapshot, plans, evidence and explicitly coordinated title/OAuth callers | Stable focused diff; full inventory and later implementation phases remain active | Scoped integration checks, pre-commit, PR and CI evidence |

Strictly necessary constructor/caller updates belong to the implementation owner
after notification to the lead. Kimi and xAI OAuth runtime persistence, Project,
Mailbox, Goal, Skill, and general Toolkit State ownership are later-phase scope.
This phase does not modify their transaction or concurrency behavior. No owner
edits shared Specs; the lead records the combined impact.

## Removal and Absence Verification

Remove SessionTitleService transaction ownership and ChatGPT OAuth runtime
session-manager/lower-repository parameters. Replace them with explicit completed
repository operations and search every affected helper caller. Remaining OAuth
and domain ownership is recorded, not hidden by an alias or generic transaction
wrapper.

## Integration and Review

Run focused owner checks before final validation. The exact independent reviewer
is `/root/tx-review`, which
reviews read-only against Requirements, ADR, Design, this plan, current Specs,
tests, and the stable diff. Batch material corrections and rerun affected checks.

Use `uv run pytest` for changed test modules, `uv run ruff check` and
`uv run ruff format --check` for changed Python paths, and the configured
`uv run ty check --error-on-warning`. Run pre-commit at commit time and record
required GitHub CI without treating pending checks as failures.

## Context Checkpoint

Implementation checkpoint: Title and ChatGPT OAuth persistence are implemented.
The owner reports 100 focused tests plus changed-path Ruff, format, and type
checks passing. Independent review, root validation, commit, PR, and CI remain.
The six evidence-only lanes and later implementation phases continue; this phase
does not claim complete repository migration.

Scope checks must establish both that required ownership/absence work is present
and that no unapproved retry, lock, durable state, or error policy was added.
Record actual modified interfaces, tests, limitations, and residual entrypoints
before opening the PR.
