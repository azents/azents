---
title: "Subagent Mailbox Activity Wait Implementation Plan"
created: 2026-07-19
updated: 2026-07-19
tags: [backend, engine, subagent, testenv]
---

# Subagent Mailbox Activity Wait Implementation Plan

## Feature Summary

Implement [Subagent Mailbox Activity Wait and Terminal Result Delivery](subagent-mailbox-activity-wait.md) and [ADR-0168](../adr/0168-unify-subagent-communication-through-mailbox-activity.md) as an eight-PR stack.

The implementation removes `wait_agent.agent_name`, lets any current-agent mailbox message complete the wait, adds an all-descendants-idle fallback, delivers every child terminal status through queue-only `agent_result`, and preserves the existing wake behavior of all collaboration producers.

## Stack

| PR | Scope | Depends on |
| --- | --- | --- |
| 1. Design | ADR-0168 and final feature design | `main` |
| 2. Implementation plan | Phase boundaries, validation matrix, and rollout | PR 1 |
| 3. Scheduling foundation | InputBuffer scheduling mode, migration, producer classification, runner/lifecycle idle logic | PR 2 |
| 4. Terminal result delivery | Typed mailbox service, `agent_result` payload/lowering, AgentRun delivery markers, delivery repair | PR 3 |
| 5. Targetless wait and acknowledgment | Remove target input, mailbox/all-idle wait, promotion-time cursor advancement, tree invalidation | PR 4 |
| 6. Validation | Deterministic E2E, backend quality checks, migration verification, and implementation fixes | PR 5 |
| 7. Spec promotion | Living Specs, design `implemented` date, final spec review | PR 6 |
| 8. Cleanup | Remove this temporary implementation plan | PR 7 |

All PRs must be created before CI monitoring begins. The stack must merge front to back, and no PR may be merged without explicit user approval.

## Phase 1 — Scheduling Foundation

### Runtime and data changes

- Add required InputBuffer scheduling mode values `queue_only` and `wake_session`.
- Generate an Alembic migration that backfills current inputs by kind and mailbox `message_kind`.
- Require every input producer to provide scheduling intent explicitly.
- Add repository/service queries for any pending input, pending wake-producing input, and pending agent mailbox input.
- Use only wake-producing pending input when determining terminal follow-up work, stop requeue, and atomic idle eligibility.
- Preserve FIFO preparation and every existing broker wake call.
- Reconcile stale running sessions through the locked lifecycle predicate rather than a blind state update.

### Tests

- InputBuffer repository/service scheduling persistence and queries.
- Producer classification for user, action, goal, spawn, send, and follow-up inputs.
- Runner and lifecycle behavior with queue-only-only, wake-producing, command, active Run, and mixed FIFO states.
- Migration upgrade coverage and historical row mapping.

## Phase 2 — Terminal Result Delivery

### Runtime and data changes

- Replace the toolkit-private generic mailbox helper with typed operation methods.
- Add the `agent_result` mailbox payload variant and `AGENT_RESULT` model envelope.
- Add AgentRun parent-result delivery state, source buffer ID, and timestamp fields.
- Backfill historical terminal subagent Runs as `suppressed` to prevent replay.
- Deliver terminal results to the direct parent for `completed`, `failed`, `stopped`, `interrupted`, and `cancelled`.
- Perform buffer creation and Run delivery marker update in one locked transaction.
- Attempt repair at terminal boundary, parent wait observation, and source-session reuse.
- Keep terminal result delivery queue-only and best-effort with structured failure reporting.

### Tests

- Five-status content and safety matrix.
- Direct-parent and same-tree validation.
- Concurrent delivery idempotency and transaction rollback.
- Historical suppression migration.
- Shared model-input lowering for every supported provider path.
- No broker wake or parent Run-state mutation for result delivery.

## Phase 3 — Targetless Wait and Acknowledgment

### Runtime and API changes

- Remove `agent_name` from `WaitAgentInput` and reject unknown fields.
- Default `timeout_seconds` to 30, retain the 0 through 600 range.
- Observe any pending mailbox message for the current agent.
- Evaluate all descendants for no-descendant, all-idle, and timeout outcomes.
- Give mailbox activity priority and perform final mailbox/activity rechecks.
- Return summaries only; never return or consume mailbox content.
- Advance the source child observation cursor only when `agent_result` is promoted into the parent transcript.
- Make cursor updates monotonic and publish Subagent Tree invalidation after promotion.
- Update model-visible subagent toolkit guidance.

### Tests

- Tool schema and removed target validation.
- Any-sender mailbox completion.
- No-descendant, all-idle, active timeout, zero-timeout, and race recheck behavior.
- Cursor remains unread through enqueue and wait return, then clears at promotion.
- Concurrent waits do not consume mailbox input.
- Existing ordinary task/message envelopes remain unchanged.

## Validation PR

### Required backend commands

Run from `python/apps/azents`:

```console
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest <focused subagent, input-buffer, runner, lifecycle, event-lowering, chat, and repository tests>
```

Run the complete affected backend suite when focused tests reveal shared execution-loop impact.

### Primary deterministic E2E matrix

| Scenario | Required evidence |
| --- | --- |
| Intermediate child message ends wait | generic wait tool result followed by exact mailbox envelope in the next model request |
| Either of two children can end wait | no target argument and sender-independent completion |
| Child completion delivers once | one `AGENT_RESULT`, one terminal Run projection, no duplicate after later turn |
| Idle parent receives result | parent remains idle until another wake-producing input |
| Queue-only terminal boundary | child session reaches idle with pending queue-only input allowed |
| All descendants idle | immediate non-timeout summary |
| No descendants | immediate no-descendant summary |
| Active descendant timeout | `timed_out = true` with active path summary |
| Interrupted child | safe interrupted result envelope |
| Failed child | sanitized failure content without internal exception text |
| Unread transition | true while queued, false only after parent promotion |

### Fixture and prerequisite support

- Reuse deterministic dummy-key/AIMock subagent setup.
- Update scripted exchanges to use targetless `wait_agent` and to produce intermediate and terminal mailbox messages.
- Do not write directly to the product database from E2E.
- No live external credentials, OAuth snapshots, runtime-provider credentials, or optional prerequisites are required.

### CI policy

- Backend unit/integration tests run in required Python checks.
- Product behavior runs in the required credential-free deterministic E2E lane.
- Missing deterministic fixtures or expected evidence is a failure, not a skip.
- CI monitoring begins only after all eight PRs are open.

## Spec Promotion

Run `/spec-review` against the completed implementation, then update:

- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/domain/toolkit.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/chat-session-resync.md`

Set `implemented: 2026-07-19` on the feature design only after implementation and validation are complete. ADR-0168 remains immutable after adoption.

## Rollout and Compatibility

- No feature flag is required.
- The targetless tool schema is exposed only after scheduling and terminal delivery foundations are present.
- Calls that still include `agent_name` fail validation; no legacy fallback is provided.
- Historical terminal results are not replayed into parent model context.
- Existing terminal result projections remain available in the Subagent Tree.
- Broker message types and source-owned wake behavior do not change.

## Known Blockers and Manual Actions

No external blocker is known. The work requires a generated Alembic migration and deterministic E2E fixture updates, both owned by the implementation stack.

PR merging is a manual action requiring explicit user approval and is outside the implementation goal.

## Cleanup

After validation and spec promotion, remove this implementation plan. The long-term sources of truth are the adopted ADR, implemented design, current Living Specs, and code.
