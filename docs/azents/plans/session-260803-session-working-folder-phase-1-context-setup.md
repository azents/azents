---
title: "Session Working Folder Phase 1 Execution Plan"
created: 2026-08-03
updated: 2026-08-03
tags: [session, workspace, persistence, mailbox, runtime, backend]
---

# Phase Execution Plan

- Phase: `1 — Context persistence and setup Action`
- Branch/base:
  `feat/session-working-folder-1-context-setup` →
  `main`
- PR boundary: Persist the exact context-owned Session working-folder path and
  bounded cleanup metadata, then enqueue and execute the system-only,
  non-blocking folder setup action for new, adopted, and restored Sessions.
- Inputs:
  - confirmed `session-260803/REQ`;
  - accepted `session-260803/ADR-D1` through `ADR-D4`;
  - approved `session-260803/DESIGN` revision 1 with authority `M1` through
    `M11`;
  - current conversation, workspace, Runtime persistence, and execution-loop
    Specs;
  - linear migration head recorded by
    `python/apps/azents/db-schemas/rdb/revision`.
- Deliverables:
  - exact generated
    `/workspace/agent/.azents/sessions/{root_session_handle}` stored on every
    root `SessionAgentContext`;
  - bounded folder-cleanup state, summary, and terminal timestamp fields;
  - generated expand/backfill migration with populated-path uniqueness and no
    Runtime or filesystem I/O;
  - system-only `create_session_working_folder` durable action discriminator;
  - queue-first initial enqueue using `QUEUE_ONLY`, without waking an otherwise
    empty Session;
  - FIFO-first execution before requested worktree setup or user input;
  - deterministic next-input adoption for active contexts and queue-only restore
    enqueue;
  - idempotent setup through existing Runner `file.mkdir`;
  - bounded terminal success/failure evidence with failure continuing later FIFO
    work and `context_invalidated = false`;
  - user-authored action request rejection while durable/live action projections
    remain decodable;
  - regenerated OpenAPI and public clients if response schemas change.
- Non-goals:
  - Runtime prompt or omitted-command-workdir changes;
  - Projects manifest entry, retry route, or Web UI;
  - Session-folder root mutation guards;
  - new worktree placement or legacy worktree cleanup changes;
  - archive folder deletion or Runner delete semantics;
  - final non-null contract migration;
  - Runtime-reset setup coordinator;
  - living-Spec promotion or E2E completion.
- Interfaces:
  - `working_folder_path` is assigned from the already-generated root Session
    handle during context creation and is the only later path authority.
  - The expand schema permits null only as a rollout shape; migration backfill
    and all new writes populate the field.
  - Cleanup state starts `not_attempted`; Phase 1 does not transition it.
  - `create_session_working_folder` accepts no target path, user identity, or
    client-selected filesystem data.
  - The first system action uses `QUEUE_ONLY`. A later setup action or user input
    may use its existing wake behavior and therefore causes FIFO processing.
  - Existing-directory and created-directory outcomes are terminal success.
  - Runtime unavailable, malformed stored path, file target, symlink target, and
    Runner failure are terminal failure and do not block later model work.
  - Existing `file.mkdir` with `parents=True` is the Runner protocol boundary.
  - Durable action claims, owner-generation fencing, cancellation, takeover,
    live projection, and terminal history reuse the existing action-execution
    infrastructure.
  - Initial creation, adoption, and restore have distinct deterministic
    idempotency scopes.
  - Public user-authored action input excludes the new system discriminator.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M10` adoption and restore
  enqueue.
- Authority references:
  `session-260803/REQ-1`, `REQ-2`, `REQ-5`, `REQ-6`, `REQ-7`;
  `session-260803/ADR-D1`, `ADR-D4`; approved Design revision 1; current
  conversation, workspace, Runtime persistence, and execution-loop Specs.
- Design delta: `None`
- Removal obligations:
  - prevent durable setup completion from becoming a physical-existence source
    of truth;
  - keep user-authored action inputs free of the system discriminator;
  - do not derive paths at any use boundary after the creation/backfill write.
- Absence verification:
  - searches and tests show setup/cleanup consumers read
    `working_folder_path`;
  - no physical setup-state enum or Project registry row is introduced;
  - public action-write tests reject `create_session_working_folder`;
  - no Runtime reset, archive, worktree allocation, command workdir, Project
    Browser, or UI behavior appears in the Phase 1 diff.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Persistence and migration | `/root` | `python/apps/azents/src/azents/core/enums.py`; `python/apps/azents/src/azents/rdb/models/session_agent_context.py`; `python/apps/azents/src/azents/repos/agent_session/{data.py,__init__.py,repository_test.py}`; `python/apps/azents/db-schemas/rdb/**`; focused model/migration tests | Root Session handle and shared context ownership | Exact stored path, cleanup fields, expand/backfill revision, repository projections and queries | Alembic head/history, migration tests, repository tests, Ruff, Pyright |
| Action contracts and mailbox enqueue | `/root` | `python/apps/azents/src/azents/engine/events/action_messages.py`; `python/apps/azents/src/azents/services/{mailbox.py,mailbox_test.py,agent_session_input.py,agent_session_input_test.py}`; `python/apps/azents/src/azents/services/chat/{__init__.py,mailbox_test.py,team_session_test.py}`; relevant public action data/write tests | Stored context path and existing mailbox FIFO | Internal system action, queue-first creation, adoption, restore, input rejection | Focused mailbox, session-input, chat, repository, and API tests |
| Setup execution | `/root` | new focused `python/apps/azents/src/azents/services/session_working_folder*.py`; `python/apps/azents/src/azents/worker/run/{executor.py,executor_test.py}`; dependency wiring required by those services | Internal action contract and existing Runner `file.mkdir` | Idempotent setup execution, bounded results, terminal failure continuation | Focused service/executor tests, Runner-operation contract regression, Ruff, Pyright |
| Public projections and generated artifacts | `/root` | public chat action response schemas and tests; `python/apps/azents/specs/public/openapi.json`; generated Python and TypeScript public clients | Stable internal versus user-authored union split | Decodable system execution/history without user write authority | OpenAPI dump/check, client generation, generated-client tests/typecheck |
| Plans and integration | `/root` | approved snapshot documents; `docs/azents/plans/session-260803-session-working-folder-{implementation-plan,phase-1-context-setup}.md`; shared integration files | All Phase 1 workstreams | Stable integrated diff and context checkpoint | Authority/removal audit, combined focused checks, `git diff --check` |
| Independent review | `hardtack` | Read-only complete Phase 1 PR diff | Stable implementation and validation evidence | Critical/Warning findings or explicit approval | GitHub review against fixed criteria below |

- Integration order:
  1. Add the model/repository contract and generate the expand migration through
     `alembic revision`; update the recorded revision.
  2. Add the internal system-action model and separate it from user-authored
     action input.
  3. Enqueue setup before all requested setup/user work for both Session creation
     paths, then add adoption and restore enqueue with distinct idempotency.
  4. Implement the folder service using stored-path validation and existing
     Runner `file.mkdir`.
  5. Dispatch the action through the existing operation-action claim loop and
     prove non-blocking terminal failure.
  6. Regenerate OpenAPI and public clients if the response contract changes.
  7. Run focused tests and quality checks, then audit scope and removal
     obligations.
  8. Request read-only review from `hardtack`, batch required corrections, rerun
     affected validation, and request targeted re-review only for requirements,
     security/data-loss, or material interface corrections.
- Independent review:
  - Exact reviewer: GitHub reviewer `hardtack`.
  - Scope: complete Phase 1 diff against `M1`, `M2`, `M3`, the adoption/restore
    portion of `M10`, this phase contract, and current Specs.
  - Criteria: exact stored path is authoritative; migration is linear and has no
    filesystem I/O; no public user can author the system action; empty creation
    does not wake; FIFO setup precedes other work; failure is terminal and
    non-blocking; no path fallback or physical-state enum exists; bounded
    evidence contains no unbounded Runner output; later-phase behavior is absent.
  - Inputs: Requirements, ADR, approved Design and Authority, implementation
    plan, this execution plan, stable diff, migration output, generated artifacts,
    and validation results.
  - Output: grounded Critical/Warning findings or explicit no findings.
- Final validation:
  - `cd python/apps/azents/db-schemas/rdb && uv run alembic heads`
  - migration upgrade/backfill and linear-chain tests selected from the existing
    migration test suite
  - focused repository, mailbox, session-input, chat lifecycle, action execution,
    worker executor, and public action-schema tests
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - `cd python/apps/azents && uv run pyright`
  - OpenAPI dump and public-client regeneration/checks when schema output changes
  - generated Python public-client focused tests
  - `cd typescript && pnpm run typecheck --filter=@azents/public-client` when the
    TypeScript generated client changes
  - `python -m pytest scripts/tests/test_gen_docs_index.py -q`
  - `git diff --check`
- Scope-drift check:
  - Verify every Phase 1 deliverable maps to `M1`, `M2`, `M3`, or the
    adoption/restore portion of `M10`.
  - Verify no approved Phase 1 behavior is missing.
  - Remove prompt/workdir, manifest/UI, root-mutation, worktree-placement,
    archive/delete, contract-migration, Runtime-reset-coordinator, or spec-promotion
    changes unless a minimal generated response artifact is strictly required by
    the Phase 1 action projection.
  - Return to feature design if implementation needs a new retry mode, state
    machine, ownership source, fallback path, or execution-admission gate.
- Context checkpoint:
  - Before commit, record completed behavior, generated migration revision and
    backfill evidence, changed repository/action/public interfaces, exact
    validation commands and results, generated artifacts, removal/absence audit,
    nullable-contract work remaining for Phase 4, Phase 2 inputs, risks, and
    blockers.
