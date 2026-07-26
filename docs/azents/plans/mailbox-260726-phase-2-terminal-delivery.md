---
title: "Unified Agent Input Mailbox Phase 2: Atomic Terminal Delivery"
created: 2026-07-26
updated: 2026-07-26
tags: [agent, mailbox, subagent, backend, transaction, plan]
---

# Unified Agent Input Mailbox Phase 2: Atomic Terminal Delivery

## Phase Execution Plan

- Phase: `2 — Producer orchestration and atomic descendant terminal delivery`
- Branch/base: `feature/mailbox-260726-producers` → `feature/mailbox-260726-persistence`
- PR boundary: Preserve the established mailbox producer scheduling contract while replacing eventual direct-parent terminal-result repair with one transaction-aware finalization coordinator that atomically finalizes every eligible child Run and prepares its queue-only direct-parent mailbox item or explicit suppression state.
- Inputs: [`mailbox-260726/REQ`](../requirements/mailbox-260726-unified-agent-input-mailbox.md), [`mailbox-260726/ADR`](../adr/mailbox-260726-unified-agent-input-mailbox.md), [`mailbox-260726/DESIGN`](../design/mailbox-260726-unified-agent-input-mailbox.md), [the multi-phase implementation plan](mailbox-260726-implementation-plan.md), and [Phase 1 execution plan](mailbox-260726-phase-1-persistence.md).
- Deliverables:
  - A shared transaction-aware terminal finalization coordinator owns child Run terminal state, direct-parent eligibility, queue-only mailbox result admission, and final enqueued/suppressed marker persistence.
  - Every direct terminal transition uses that coordinator: normal Engine completion, failed/unhandled finalization, pending cancellation, individual lifecycle terminal marking, Session-wide mass close, and User Stop individual/bulk finalization.
  - Completed, failed, stopped, interrupted, and cancelled eligible descendants commit their terminal projection with exactly one idempotent parent mailbox result in the same transaction.
  - Queue-only terminal result admission never ensures the parent Session is running and never sends `SessionWakeUp`.
  - Existing terminal-boundary, parent-wait, and source-session-reuse repair paths are removed only after all direct callers have coordinator coverage.
  - Producer orchestration remains explicit: full-wakeup producers retain their existing durable running-state plus post-commit wake workflow; queue-only producers remain non-waking.
- Non-goals:
  - Do not add live-owner mailbox activity transport, observer notification, generalized `wait`, or `WaitToolkit`; Phase 3 owns them.
  - Do not rename public REST/OpenAPI fields, WebSocket actions, generated clients, or Web state; Phase 4 and 5 own those contracts.
  - Do not modify the Phase 1 mailbox table/payload migration except a narrowly required correctness fix discovered by Phase 2 tests.
  - Do not add a fallback terminal-delivery store, dual delivery path, or wait-driven repair.
  - Do not change direct human write permissions for subagent Sessions.
- Interfaces:
  - `TerminalRunFinalizationCoordinator` (or equivalent) receives the caller's DB transaction/session and terminal outcome, locks the required root tree, child Run, and direct parent in one established order, creates/returns an idempotent queue-only `AgentMessageMailboxPayload`, and records final delivery state.
  - The coordinator returns a structured finalization outcome distinguishing parent result `enqueued`, `suppressed`, or ineligible/no-op without exposing message content to callers.
  - All legacy repository terminal methods either delegate to the coordinator or become lower-level transaction helpers that cannot independently finalize eligible child Runs.
  - Terminal result payload preserves current safe result text, child identity, terminal status, run identity, mailbox item identity, and stable item key.
  - Promotion-time direct-parent observation acknowledgement remains coupled to durable event append and mailbox deletion; it is not terminal-finalization repair.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Terminal finalization and producer orchestration | `/root/mailbox-implementer` | `python/apps/azents/src/azents/engine/events/execution.py`; `engine/events/finalization.py`; `worker/run/{executor,finalizer}.py`; `worker/session/{lifecycle,user_stop_finalizer,runner}.py`; `services/subagent_terminal_result.py`; `services/agent_mailbox.py`; `repos/agent_execution/**`; relevant models/services/tests; phase-local migration only if essential | Phase 1 mailbox contracts | Coordinator, caller cutover, repair removal, terminal tests | Focused terminal/lifecycle/executor/subagent tests, full backend quality/tests, docs validation |
| Independent review | `/root/mailbox-reviewer` | Read-only complete Phase 2 diff and evidence review | Implementation owner validation | Critical/Warning findings and recheck | Transaction boundaries, all-caller inventory, queue-only scheduling, duplicate delivery, lock order, repair removal timing |

- Integration order:
  1. Inventory every non-test direct terminal write and terminal repair call. The inventory must include Engine execution `_mark_terminal`, failed event finalization, RunExecutor unhandled finalization, pending Run cancellation, individual lifecycle terminal marking, Session-wide remaining-Run marking, User Stop individual/bulk finalization, and `SubagentTerminalResultService` repair entry points.
  2. Define the coordinator input/outcome types and exact lock order. Reuse current root tree locking where compatible; do not introduce a lock cycle.
  3. Move normal completed, failed, stopped, interrupted, and cancelled child finalization into the coordinator transaction with direct-parent mailbox admission and delivery marker update.
  4. Move pending cancellation and bulk/session-wide close through the same coordinator for every eligible child, including explicit suppressed marker handling.
  5. Preserve safe terminal-result content and idempotent retry convergence. Verify duplicate terminal retries do not enqueue another mailbox item.
  6. Delete terminal-boundary, parent-wait, and source-session-reuse repair calls only after tests prove all caller coverage. Keep promotion-time observation acknowledgement intact.
  7. Verify producer admission preserves `wake_session` versus `queue_only` semantics and that terminal results remain queue-only.
  8. Run implementation-owner validation, directly request review from `/root/mailbox-reviewer`, apply findings, rerun affected checks, and request recheck before reporting completion.
- Independent review: `/root/mailbox-reviewer` performs read-only review. Critical criteria are any terminal caller that can commit an eligible child Run before parent mailbox delivery/explicit suppression, a separate repair path retained as delivery authority, parent running-state mutation or `SessionWakeUp` for a terminal result, duplicate envelope risk, incorrect direct-parent selection, lock-order cycle/deadlock risk, or deletion of promotion-time observation acknowledgement. Warnings include missing status/caller rollback tests, unsafe safe-text regression, incomplete metrics/logging, or tests that do not distinguish active versus idle parent behavior.
- Final validation:

  ```bash
  cd python/apps/azents
  uv run ruff check .
  uv run ruff format --check .
  uv run pyright .
  uv run pytest -q \
    src/azents/services/subagent_terminal_result_test.py \
    src/azents/worker/run/finalizer_test.py \
    src/azents/worker/run/executor_test.py \
    src/azents/worker/session/lifecycle_test.py \
    src/azents/worker/session/user_stop_finalizer_test.py \
    src/azents/worker/session/runner_test.py \
    src/azents/engine/events/execution_test.py
  uv run pytest -q

  cd ../../..
  python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check
  ```

  The implementation owner must correct any stale targeted test path in this phase plan before substituting it. Phase 2 must add transaction rollback tests for every terminal status and direct caller, duplicate retry tests, direct-parent eligibility/suppression tests, active-parent versus idle-parent scheduling tests, and repair-removal regression tests.
- Scope-drift check: Compare `git diff --stat` and `git diff feature/mailbox-260726-persistence...HEAD` with the deliverables and non-goals. Reject Redis activity transport, observer/TurnContext fields, `wait` Toolkits/prompts, public API rename, generated clients, Web state/rendering, broad mailbox schema refactors, spec promotion, and unrelated cleanup. Confirm no terminal repair call survives as a source of mailbox production after coordinator coverage is complete.

## Terminal Caller Coverage Matrix

| Terminal source | Required coordinator behavior | Required test |
| --- | --- | --- |
| Normal Engine completion | terminal Run + eligible parent result atomically commit | completed child delivers one queue-only envelope |
| Engine stopped/interrupted branch | terminal Run + safe status/result atomically commit | stopped/interrupted child result preserves safe fallback |
| Failed event finalization / unhandled executor failure | failed Run + parent result atomically commit | failure rollback leaves neither partial terminal nor orphan mailbox result |
| Pending Run cancellation | cancelled child receives parent result or explicit suppression in same transaction | cancellation cannot bypass direct-parent delivery |
| Individual lifecycle terminal mark | all terminal statuses use coordinator | no standalone eligible terminal repository write |
| Session-wide remaining-Run mass close | each eligible child gets independent idempotent outcome in one caller transaction scope | bulk close covers every child without duplication |
| User Stop individual and bulk finalization | stopped/interrupted/cancelled child outcome stays queue-only | idle parent remains idle and active parent is not woken yet |
| Retry/recovery of a previously attempted terminal state | existing delivery marker/envelope is reused | retry converges to one parent mailbox item |

## Repair Removal Contract

The following may not be removed until every row of the caller matrix passes coordinator tests:

- `SessionRunner` terminal-boundary delivery repair;
- parent-wait delivery repair in the current Subagent wait behavior; and
- source-session-reuse delivery repair.

After coverage is complete, remove them as production paths. The generalized wait in Phase 3 must be a pure mailbox observer and must not reintroduce terminal delivery production. Promotion-time acknowledgement of a direct-parent terminal result remains a separate transactional observation concern and is not removed by this phase.

## Scheduling Contract

| Producer | Required Phase 2 behavior |
| --- | --- |
| User message, Goal continuation, Turn Action, spawn assignment, follow-up task, External invocation | Preserve current `wake_session` producer workflow. |
| Ordinary Agent `send_message` | Preserve current `queue_only` workflow. |
| Descendant terminal result | Preserve `queue_only`; do not set parent Session running and do not send `SessionWakeUp`. Phase 3 later adds active-owner observation only. |

## Evidence Limitation

Phase 1's real database migration limitation remains open: Docker and an injected PostgreSQL target are unavailable locally, and offline SQL execution stops at historical migration `97d069ea543b` before the mailbox revision. Phase 2 must not hide or reinterpret that limitation. CI database migration coverage remains required before the stack can satisfy the overall CI-passing goal.
