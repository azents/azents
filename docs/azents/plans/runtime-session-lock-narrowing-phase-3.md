---
title: "Runtime and Session Lock Narrowing Phase 3"
created: 2026-08-07
tags: [session, postgresql, concurrency, backend]
---
# Phase Execution Plan

- Phase: `3 — Session admission lock narrowing`
- Branch/base: `fix/session-admission-lock-narrowing` → `fix/runtime-profile-resolution-cas`
- PR boundary: Narrow Session admission row locks and remove redundant Session-creation advisory locking while preserving durable REST idempotency.
- Inputs: Phase 1/2 Runtime lock narrowing and the existing `chat_write_requests` unique constraints.
- Deliverables:
  - Session, Agent, and Workspace membership admission locks use `FOR NO KEY UPDATE`.
  - `lock_session_creation_request` and both creation-path calls are removed.
  - Concurrent first-message Session creation converges through the Agent-scoped unique idempotency key instead of an advisory lock.
- Non-goals: Schema changes, public API changes, Runtime Profile resolution changes, and Git worktree path coordination advisory locks outside Session admission.
- Interfaces: Existing Session admission service results, ChatWriteRequest repository API, and Agent/Session lock helpers.
- Approved Design mechanisms: Durable REST idempotency, transactional Session admission, and narrower PostgreSQL locks that preserve FK KEY SHARE compatibility.
- Authority references: `session-260724/REQ-1`, `session-260724/REQ-4`, `session-260806/REQ`; [Conversation Domain](../spec/domain/conversation.md).
- Design delta: `None`
- Removal obligations: Remove `ChatWriteRequestRepository.lock_session_creation_request` and both Agent Session creation call sites.
- Absence verification: Repository searches show no remaining `lock_session_creation_request` references; concurrent creation tests pass without advisory locking.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Admission locks | root | `repos/agent_session/`, `repos/agent/`, `repos/workspace_user/` | Existing lock helpers | `FOR NO KEY UPDATE` admission locks | Repository/service tests |
| Creation idempotency | root | `repos/chat_write_request/`, `services/agent_session_input.py` | Unique creation key | Advisory-lock-free concurrent creation | Concurrent first-message tests |

- Integration order: Narrow admission locks → remove advisory lock → recover losing creators through unique-key replay → focused quality checks.
- Independent review: `hardtack` reviews admission lock strength, unique-key convergence, and absence of the removed advisory API.
- Final validation: `uv run pytest` for agent_session_input, chat_write_request, workspace_user, and agent_session focused suites; Ruff; format; ty; pre-commit.
- Scope-drift check: Preserve current REST idempotency contract and Session creation APIs; no schema or public client changes.
- Context checkpoint: Phase 3 owns Session admission lock narrowing only. Runtime worktrees outside admission keep their existing coordination locks.
