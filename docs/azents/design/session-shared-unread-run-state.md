---
title: "Session-Shared Unread Run State"
created: 2026-07-20
updated: 2026-07-20
implemented: 2026-07-20
tags: [conversation, backend, frontend, api, ux]
document_role: supporting
document_type: supporting-consolidation
migration_source: "docs/azents/design/session-shared-unread-run-state.md"
supporting_role: consolidation
---

# Session-Shared Unread Run State

## Overview

Azents will show a small unread indicator in the Agent rail when an active root AgentSession has a terminal Run that has not yet been reviewed in the latest visible Chat timeline. The unread state is shared by the Session: review by any authorized workspace member clears it for everyone.

This design implements [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-270). It does not introduce user-specific notifications, change Session ordering, or add unread behavior to subagent or archived Session surfaces.

## Problem

AgentSessions can continue running after the user navigates elsewhere. The Agent rail currently shows whether a Session is running, but once the Run returns to idle there is no durable indication that a terminal result is waiting for review.

The existing fields do not represent this state:

- `AgentSession.run_state` represents current execution control, not review state.
- `AgentSession.updated_at` includes unrelated Session mutations and cannot identify which Run was reviewed.
- `AgentSession.last_user_input_at` owns Session ordering and records human input rather than Run completion.
- Browser-local state would diverge across members, browsers, and devices.

## Goals

- Mark an eligible Session unread whenever one of its Runs first transitions to any terminal status.
- Keep unread state shared across all workspace members.
- Clear unread only after the latest Chat timeline has been successfully resynced and rendered in a visible document.
- Make acknowledgement race-safe when a newer Run becomes terminal concurrently.
- Show one small accent dot without changing Session ordering.
- Treat all preexisting terminal Runs as already reviewed at rollout.

## Non-Goals

- User-specific read receipts, notifications, inboxes, counts, or notification delivery.
- Unread state for subagent Sessions.
- Unread presentation or lifecycle behavior for archived Sessions.
- Reordering Sessions by unread or terminal Run time.
- Adding new timeline cards for terminal statuses that currently have no visible result item.
- Mark-unread actions.

## Current Behavior

- `agent_runs.run_index` is monotonic within one Session and every Run has a durable status.
- Terminal statuses are `completed`, `failed`, `stopped`, `interrupted`, and `cancelled`.
- Terminal transitions converge through `AgentRunRepository.mark_terminal()`, `mark_terminal_if_running()`, and `mark_session_running_terminal()`.
- `GET /chat/v1/agents/{agent_id}/sessions` returns active root Sessions, with team primary first and remaining Sessions ordered by `last_user_input_at`.
- The Agent rail polls the Session list every five seconds and already displays a running spinner from `run_state`.
- Chat initial entry and resume use the subscribed/health-check/history/live resync transaction. `useChatSessionContainer` distinguishes `LATEST_FOLLOWING` from `DETACHED_HISTORY_BROWSING`.

## Product Decisions

1. Unread state is shared by the Session.
2. Every terminal Run status creates unread state, including cancellation before useful model output.
3. Route entry alone does not clear unread.
4. Review is acknowledged after a fresh latest timeline is rendered while the document is visible.
5. Hidden documents, failed/incomplete resync, and detached history browsing do not acknowledge review.
6. Only active root Sessions participate.
7. Archived Sessions receive no feature-specific unread behavior.
8. The Agent rail shows a small accent dot only.
9. Existing ordering remains unchanged.
10. Existing terminal Runs are read at rollout; only later terminal transitions create unread state.

## Data Model

Add a sparse one-to-one table:

### `agent_session_unread_runs`

| Column | Type | Meaning |
| --- | --- | --- |
| `session_id` | `str(32)` PK, FK to `agent_sessions.id` | Session whose terminal Run requires review. |
| `run_id` | `str(32)` FK to `agent_runs.id` | Current unread terminal Run boundary. |
| `run_index` | bigint | Session-scoped monotonic boundary used for race-safe replacement and acknowledgement. |
| `created_at` | timestamptz | First unread boundary creation time. |
| `updated_at` | timestamptz | Last replacement time. |

Constraints:

- `run_index > 0`.
- `run_id` is unique.
- `session_id` and `run_id` use cascading deletion so Session purge removes unread state naturally.

The table is sparse:

- Row exists: Session is unread through the recorded terminal Run.
- Row absent: Session is read.

A separate table is preferred over columns on `agent_sessions` because review and terminal transitions must not modify the general Session `updated_at`, which is displayed in the rail and participates in the existing ordering fallback.

No historical rows are inserted by the migration. This makes every preexisting terminal Run read by definition.

## Terminal Transition Behavior

Unread creation is part of the same database transaction that first changes an AgentRun into a terminal status.

For one terminal Run `(session_id, run_id, run_index)`:

1. Transition the Run to its terminal status.
2. Verify the owning Session is currently `active` and `session_kind = root`.
3. Insert `agent_session_unread_runs`.
4. On `session_id` conflict, replace the boundary only when the incoming `run_index` is greater than the stored `run_index`.

The write must happen only on a real nonterminal-to-terminal transition. Replaying an idempotent terminal finalizer after the Session was reviewed must not recreate unread state.

`mark_session_running_terminal()` may transition more than one stale running row. It uses the greatest returned `run_index` as the unread boundary.

Subagent and archived Sessions do not produce unread rows. Archive and restore flows do not read, clear, copy, or reset this table.

## Review Acknowledgement

The client acknowledges the terminal Run it actually observed rather than requesting that the server clear whichever Run is currently latest.

Given an observed terminal Run with index N, the repository conditionally deletes:

```text
session_id = target session
AND stored run_index <= N
```

This gives the required race behavior:

1. Client renders Run N.
2. Run N+1 becomes terminal and replaces the unread boundary.
3. Client acknowledgement for Run N arrives.
4. The conditional delete does not match N+1, so the Session remains unread.

Acknowledgement is idempotent. A missing row is already read and returns success.

For a terminal status that produces no dedicated timeline item, such as an early cancellation, successful rendering of the authoritative latest history/live baseline still constitutes review. This design does not add a synthetic cancellation card solely to support unread acknowledgement.

## API Design

### Session projection

Add this required nullable field to `AgentSessionResponse`:

| Field | Type | Meaning |
| --- | --- | --- |
| `unread_terminal_run_id` | `string | null` | Current shared unread terminal boundary; null means read. |

The field is returned by both Agent Session list and detail routes. Public API projection composes AgentSession domain data with the sparse unread row; unread state does not become execution-control state on the core `AgentSession` domain model.

Fresh Session creation returns `unread_terminal_run_id = null` explicitly.

### Acknowledge endpoint

```text
POST /chat/v1/agents/{agent_id}/sessions/{session_id}/read
```

Request:

```json
{
  "through_run_id": "<terminal AgentRun ID>"
}
```

Response: `204 No Content`.

Validation:

- Requester is a member of the Session workspace.
- Session matches `agent_id`, is active, and is a root Session.
- Run exists, belongs to the Session, and is terminal.
- Missing Session, membership, or mismatched Run returns the existing 404-safe access response.
- A nonterminal Run returns `409 Conflict`.
- An already-read or older boundary remains a successful idempotent request.

The endpoint does not accept a client-provided `run_index`; the server resolves the validated Run ID.

Public OpenAPI specifications and generated Python/TypeScript clients are regenerated with the route and field.

## Backend Architecture

### Repository responsibilities

- Add `RDBAgentSessionUnreadRun` under the conversation RDB models.
- Extend terminal transition methods in `AgentRunRepository` so terminal state and unread boundary commit atomically.
- Add a conditional acknowledgement repository method that validates/loads the observed Run and deletes the sparse row only through that boundary.
- Add Session list/detail projection queries that left join the unread table without changing Session ordering.

### Service responsibilities

`ChatSessionService` owns access validation and acknowledgement semantics. Routes continue to call services; services call repositories.

### Atomicity

Unread creation is not a best-effort side effect. A committed terminal Run and its shared unread boundary must not disagree. Database failures propagate through the existing terminal finalization error path rather than committing a falsely read terminal Run.

## Frontend Behavior

### Agent rail

`AgentFocusedSidebar` renders a small accent dot beside the Session title when `unread_terminal_run_id !== null`.

- The dot uses Mantine theme color variables and `rem()` sizing.
- The visible title is not made bold.
- No `Unread` text badge is added.
- An accessible label describes the unread terminal result.
- The existing running spinner remains independent. A Session may show both a spinner and an unread dot when a previous terminal Run remains unreviewed while a newer Run is active.
- Session array ordering is not modified on the client.

Add colocated Storybook states for read, unread, running, and running-plus-unread rows.

### Review acknowledgement coordinator

`useChatSessionContainer` already owns the state required to decide whether the latest Chat timeline has been reviewed. Add an acknowledgement effect with these conditions:

- `agentSessionQuery.data.unread_terminal_run_id` is non-null.
- A successful fresh baseline has been applied and committed to React state.
- `chatViewState.type === READY`.
- `chatTimelineState.type === LATEST_FOLLOWING`.
- Document visibility is `visible`, using the Mantine document visibility hook.
- No acknowledgement for the same Run ID is already in flight.

The successful resync increments a rendered-baseline revision state. The acknowledgement effect runs after React commits that revision, ensuring route entry and pre-render fetching do not count as review.

On success, invalidate:

- `chat.getAgentSession({agentId, sessionId})`
- `chat.listAgentSessions({agentId})`

Do not optimistically clear the dot. If acknowledgement fails, durable unread state remains and a later successful resync or visibility transition retries it.

### Discovering a newly terminal Run

- Extend current Run-state reconciliation to invalidate `getAgentSession` as well as the Agent Session list when the active Session changes Run state.
- Terminal WebSocket controls and successful resync also invalidate the detail projection.
- Background Sessions rely on the existing five-second Agent Session list polling.
- No workspace-level WebSocket channel is added.

When a hidden document becomes visible, the existing resume resync runs first. Acknowledgement happens only after that resync renders the latest state.

Chat-adjacent context or subagent pages do not acknowledge review because they do not render the latest Chat timeline.

## Error Handling

- Terminal upsert failure rolls back the terminal transaction.
- Review API access and Run validation errors use typed expected errors.
- Unexpected database failures propagate to standard server error handling.
- Frontend acknowledgement failure leaves unread visible and retries on a later review-eligible transition; it does not show a blocking notification because no user action failed.
- Duplicate terminal finalization and duplicate acknowledgement remain idempotent.

## Security and Permissions

- Any authorized workspace member who can read the active root Session may acknowledge it.
- Because state is Session-shared, the server does not record which member reviewed the Run.
- Session/run membership validation prevents a Run ID from clearing another Session.
- 404-safe access behavior avoids revealing Session or Run existence across workspaces.

## Migration and Rollout

1. Generate an Alembic revision that creates the empty `agent_session_unread_runs` table.
2. Update the RDB revision pointer.
3. Deploy schema before application code that writes unread boundaries.
4. Deploy backend terminal integration, projection/API, generated clients, and frontend together as one feature change.
5. Do not add legacy fallbacks or dual-write paths.

Rollback drops the sparse table after rolling back application code. There is no historical data conversion because the initial table is empty by design.

## Observability

Structured logs should include `session_id`, `run_id`, and `run_index` when a terminal transition cannot update unread state or an acknowledgement fails unexpectedly. Normal successful upserts and acknowledgements do not require per-event info logs.

## Alternatives Considered

### Boolean column on `agent_sessions`

Rejected because a boolean cannot safely distinguish acknowledgement of Run N from a concurrently completed Run N+1. Updating the Session row would also disturb its general `updated_at` display and ordering fallback.

### Latest/reviewed cursor columns on `agent_sessions`

Race-safe but rejected because unread review is an auxiliary sparse projection, not Session execution-control state. It would still mutate the general Session row on every completion and review.

### Derive unread from `agent_runs.ended_at` and Session timestamps

Rejected because no current Session timestamp represents shared review, and time comparison is less precise than the existing monotonic Run index.

### User/session read receipt table

Rejected by the product decision that review is shared by the Session.

### Notification row per terminal Run

Rejected because this feature needs one current Session indicator, not an inbox, history, count, or delivery lifecycle.

## Test Strategy

### E2E primary verification matrix

| Scenario | Expected result |
| --- | --- |
| Run completes while user is on another Session | Source Session shows an unread dot after list refresh. |
| Run fails, stops, interrupts, or cancels | Eligible root Session becomes unread for every terminal status. |
| Member opens unread Session in a visible document | Dot remains through route/load, then clears only after latest resync renders. |
| Session opens in a hidden document | Dot remains until visibility-triggered resync renders the latest timeline. |
| User browses detached historical pages | Dot remains until reset-to-latest completes. |
| Two members view the same workspace | Review by one member clears the dot for the other after polling. |
| Run N+1 completes while acknowledgement for Run N is in flight | Session remains unread for Run N+1. |
| Subagent Run completes | No Agent rail unread state is created. |
| Existing terminal Runs after migration | No unread dots appear until a new terminal transition occurs. |
| Running Session with older unread boundary | Running spinner and unread dot are both visible without reordering. |

### E2E plan

- Add Playwright coverage using two authenticated browser contexts for the shared acknowledgement scenario.
- Use deterministic local execution or seeded terminal transitions; no live external model credential is required for the required CI path.
- Exercise visible, hidden, and detached timeline states through real route/resync behavior rather than directly calling the acknowledgement API.
- Capture screenshots for dot presentation and traces for failed scenarios.

### Testenv support

Testenv fixture support is needed to create:

- One Agent with multiple active root Sessions.
- Two workspace members.
- Terminal Runs for each terminal status.
- A running Session with an older unread boundary.
- A root Session and child subagent Session pair.

Fixtures should create state through repository/service helpers where practical. Direct table seeding is acceptable only for race setup that cannot be produced deterministically through public flows.

No credential or live-provider snapshot is required. Optional live-provider smoke tests may run when credentials are available, but they are not primary evidence.

### Backend tests

- RDB model constraints and migration upgrade/downgrade.
- Each terminal status creates an unread row for active root Sessions.
- Subagent and archived Sessions do not create rows.
- A higher Run index replaces a lower unread boundary.
- Duplicate terminal finalization after acknowledgement does not recreate unread state.
- Acknowledgement through an older Run cannot clear a newer boundary.
- Acknowledgement through the current/newer observed terminal Run clears the row.
- List/detail projections expose the correct nullable Run ID without changing ordering.
- API access, Session/run mismatch, nonterminal conflict, and idempotent success.

### Frontend tests

- Pure Session row stories for read/unread/running combinations.
- Acknowledgement effect does not run during loading, hidden visibility, or detached browsing.
- Acknowledgement runs after a committed latest baseline render.
- Query invalidation occurs only after successful acknowledgement.
- Failed acknowledgement preserves the indicator and can retry later.
- Session ordering remains the server-provided ordering.

### Evidence and CI policy

Required CI evidence:

- Backend Ruff, Pyright, and targeted Pytest results.
- TypeScript format, lint, typecheck, and build results.
- Generated client consistency.
- Required deterministic Playwright E2E matrix results with trace retention on failure.
- Storybook build or targeted story test for the new indicator states.

Required deterministic tests fail CI on any failure or skip. Optional live-provider smoke tests may skip only when their documented credential prerequisite is absent; an available prerequisite with a failing test is a CI failure.

## Required Spec Updates

- `docs/azents/spec/domain/conversation.md`: sparse unread table, terminal transition invariant, Session response projection, and shared acknowledgement semantics.
- `docs/azents/spec/flow/chat-session-resync.md`: visible latest-render acknowledgement boundary and hidden/detached behavior.

## Open Questions

None. Product decisions are recorded in [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-271), and implementation details are defined by this design.
