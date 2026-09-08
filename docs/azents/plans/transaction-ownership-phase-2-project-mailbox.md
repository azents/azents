---
title: "Transaction Ownership Phase 2: Project, Mailbox, and Toolkit State"
created: 2026-09-08
tags: [backend, architecture, database, project, mailbox, toolkit]
---

# Phase Execution Plan

- Phase: 2, Project, Mailbox, and Toolkit State repository ownership.
- Branch/base: `refactor/project-mailbox-transactions-260908` →
  `refactor/title-repository-transactions-260908`.
- Requirements: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md).
- Decisions: [transaction-260908/ADR](../adr/transaction-260908-repository-ownership.md).
- Design: [transaction-260908/DESIGN](../design/transaction-260908-repository-ownership.md), revision 1.
- Mechanisms: M1, M2, M3, M4, M5.
- Design delta: None.
- Independent reviewer: `/root/tx-review`.
- Integration owner: `/root`.

## Scope

This phase combines three dependent corrections:

1. Project registration, removal, working-folder binding, and Skill invalidation
   use database-only composing repositories around Runtime and filesystem work.
2. Mailbox TurnAction preparation resolves attachments and managed VFS Skills
   before final promotion, then revalidates Session generation, FIFO identity,
   active filesystem Skill projection, and continuation authority inside one
   repository-owned database transaction.
3. Toolkit State, Goal, and Skill persistence types move out of mixed Engine
   modules into pure core models and database repository operations. Goal callers
   use explicit typed mutations rather than application callbacks executed inside
   repository transactions.

Owned implementation paths include:

- `python/apps/azents/src/azents/core/{goal,skill_projection,toolkit_state}.py`
- `python/apps/azents/src/azents/repos/{goal,skill_state,toolkit_state}/**`
- `python/apps/azents/src/azents/repos/mailbox/promotion.py`
- `python/apps/azents/src/azents/repos/session_workspace_project_operations/**`
- `python/apps/azents/src/azents/repos/session_working_folder_binding/**`
- `python/apps/azents/src/azents/services/{mailbox,turn_action}.py`
- `python/apps/azents/src/azents/services/session_workspace_project/**`
- `python/apps/azents/src/azents/services/session_working_folder_binding.py`
- directly affected Toolkit, Chat, Worker, API, and test callers required by the
  moved defining modules and constructor contracts.

## Preserved Atomicity and Authority

- Project finalization retains existing registry, preset, catalog, binding, and
  Skill invalidation atomic groups. Final Project authorization uses the
  canonical `Agent -> AgentSession -> membership -> binding/context ->
  Project/path` lock order.
- Skill projection synchronization reads the Project list through one completed
  repository operation, performs Runtime scanning with no database transaction,
  and writes the Skill projection through a later completed repository operation.
- Mailbox finalization retains Session-before-FIFO locking, owner-generation and
  expected-head fences, event idempotency, Goal/Skill effects, action-execution
  creation, Run association, agent-result acknowledgement, and Mailbox deletion.
- Managed VFS resolution and Runtime/filesystem operations execute with no active
  caller database transaction.
- Filesystem Skill selection and Project authority are revalidated after external
  preparation.
- No new cross-I/O lock, retry policy, durable state, Redis dependency, or
  provider failure behavior is introduced.

## Integration Completion

Before review, complete every direct `MailboxService` construction with the typed
promotion repository dependency and migrate the remaining Chat Goal callback
mutations to completed typed Goal repository operations. Update the current
Project, Toolkit, conversation/Mailbox, and execution-loop Living Specs with the
new source paths and verified behavior.

Validation includes full Ruff and format checks for affected paths, full
`uv run ty check --error-on-warning`, the Project repository/service suite,
Mailbox/TurnAction/Goal/Toolkit tests, and Session Git-worktree Skill regression
tests. The stable combined diff receives an independent read-only review from
`/root/tx-review` before handoff.

## Residual Ownership

This phase does not claim repository-wide transaction completion. Remaining
service-owned database-only transaction entrypoints outside Project, Mailbox
promotion, Toolkit State, Goal, and Skill remain assigned to later domain phases.
Mailbox admission, scheduled admission, query helpers, and other callers not
migrated by this phase remain explicit inventory items. No implemented date is
recorded until the full development snapshot is complete and verified.
