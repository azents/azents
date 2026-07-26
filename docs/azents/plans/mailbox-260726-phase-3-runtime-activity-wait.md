---
title: "Unified Agent Input Mailbox Phase 3: Runtime Activity and Wait Toolkit"
created: 2026-07-26
updated: 2026-07-26
tags: [agent, mailbox, worker, runtime, toolkit, plan]
---

# Mailbox Phase 3: Runtime Activity and Wait Toolkit

## Phase Execution Plan

- Phase: `3 — Runtime activity and Wait Toolkit`
- Branch/base: `feature/mailbox-260726-runtime-wait` → `feature/mailbox-260726-producers`
- PR boundary: Add live-owner-only mailbox activity routing and the generalized
  model-visible `wait` capability without changing producer scheduling, mailbox
  persistence, public pending projections, or Web behavior.
- Inputs: [`mailbox-260726/REQ`](../requirements/mailbox-260726-unified-agent-input-mailbox.md),
  [`mailbox-260726/ADR`](../adr/mailbox-260726-unified-agent-input-mailbox.md),
  [`mailbox-260726/DESIGN`](../design/mailbox-260726-unified-agent-input-mailbox.md),
  the [multi-phase implementation plan](mailbox-260726-implementation-plan.md),
  and the completed [Phase 2 execution plan](mailbox-260726-phase-2-terminal-delivery.md).
- Deliverables:
  - A live-owner-only, payload-free mailbox activity transport for queue-only
    admissions and observer activity for existing full Session wakeups.
  - A Run-scoped observer injected through the Engine context without exposing
    Session ownership or broker primitives to toolkits.
  - An independent `WaitToolkit` with the fixed eligibility, timeout, structured
    outcome, and concise-prompt contracts from `mailbox-260726/ADR-D6`.
  - Exactly one post-commit activity notification for each terminal path, with
    explicit handling only for terminal paths that do not return a result to the
    SessionRunner.
- Non-goals:
  - No mailbox schema, producer payload, terminal-delivery atomicity, public API,
    generated client, Web, or scheduler-wake semantic changes.
  - No compatibility alias for `wait_agent`, terminal repair restoration, or
    idle-parent startup from queue-only activity.
- Interfaces:
  - `SessionBroker.notify_mailbox_activity(session_id)` routes only to an
    existing live owner and does not queue scheduler work.
  - `MailboxActivityObserver` exposes a monotonic revision and cancellable
    `wait_after` without a mailbox payload.
  - `WaitToolkit` returns only the `activity/mailbox`, `not_waitable`, and
    `timed_out` structured outcomes; mailbox promotion remains elsewhere.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Runtime activity, observer, wait tool, producer hooks, and tests | `/root/mailbox-implementer` | `python/apps/azents/src/azents/{broker,core,engine,services,worker}/**`; Phase 3 plan | Phase 1 mailbox, Phase 2 atomic terminal finalization | Live-owner activity transport, Run-scoped observer, `WaitToolkit`, prompt migration, queue-only notification ownership | Broker/observer/wait/worker/executor/User Stop tests; full backend quality and docs checks |
| Independent review | `/root/mailbox-reviewer` | Read-only Phase 3 diff and evidence | Implementer validation | Grounded findings and recheck verdict | Producer notification matrix, idle/wake semantics, observer races/lifecycle, toolkit contract, scope boundaries |

- Integration order:
  1. Add the broker activity transport and prove no-owner or missing-runner drops
     do not create a runner.
  2. Add the Run-scoped observer, worker routing, full-wakeup observation, and
     Engine context injection.
  3. Wire queue-only `send_message` and terminal post-commit notification
     ownership, including exactly-once terminal-path regression coverage.
  4. Replace `wait_agent` with the independent `WaitToolkit`, service, concise
     prompts, and tests.
  5. Run scope-drift comparison against these deliverables and non-goals before
     review.
- Independent review: `/root/mailbox-reviewer` reviews activity routing,
  post-commit notification ownership, idle-parent preservation, observer race
  handling, Run context injection, wait/tool/prompt migration, and the complete
  Phase 3 diff. The implementation owner applies grounded findings and obtains
  a `CLEAN` recheck.
- Final validation: full backend pytest; Ruff check and format check; Pyright;
  documentation index check; `git diff --check`; and the independent `CLEAN`
  verdict.
- Scope-drift check: the final diff must be limited to runtime activity,
  observer/context, queue-only post-commit notification ownership, generalized
  wait, prompts, their tests, and this phase plan.

## Scope

Implement the runtime-only activity and wait boundary described by
`mailbox-260726/REQ-4`, `REQ-5`, `REQ-7`, and `REQ-8`, on top of the Phase 2
terminal-delivery implementation. This phase changes worker/runtime routing and
model-visible wait tooling only; it does not change mailbox persistence,
terminal admission, public API projections, or scheduler semantics.

## Fixed contracts

- Spawn assignments and follow-up tasks remain full Session wakes.
- Ordinary agent messages and terminal results remain `QUEUE_ONLY`.
- Queue-only activity may end an already-active wait but never starts or wakes an
  idle parent Session.
- Terminal delivery remains atomic in the Phase 2 coordinator; Phase 3 adds
  only post-commit live-owner activity notification.
- `wait` is an independent auto-bound `WaitToolkit`; it must not remain in
  `SubagentToolkit`, and `wait_agent` is removed without an alias or fallback.
- Activity signals carry no mailbox payload, are transient hints, and are safe to
  drop when no live owner or matching runner exists.
- The wait observer never consumes mailbox items, scheduler messages, or broker
  payloads; it re-reads durable mailbox state.

## Runtime design

### Activity transport

1. Add a typed activity-only broker signal with `session_id` and a distinct type.
2. After a queue-only mailbox commit, route the signal to the current live owner
   stream using the existing owner lock/heartbeat keys. Do not publish to the
   global stream when no live owner exists.
   - Wire the post-commit emission into ordinary `send_message` admission and
     Phase 2 terminal finalization. Their durable mailbox admission remains
     queue-only; the new emission is transient observation only.
3. Decode activity entries before the normal broker-message path. Activity
   entries are acknowledged and routed only to an existing `SessionRunner`;
   missing runners are benign drops and never create a runner.
4. Preserve full `SessionWakeUp` routing for wake-producing inputs and expose
   those wakeups as observer activity without duplicate notifications.

### Run-scoped observer

- Add a monotonic, condition-backed `MailboxActivityObserver` with
  `current_revision`, `wait_after`, `notify`, and `close`.
- Create one observer per active Engine Run in `SessionRunner`; close it before
  ownership release or handover.
- Pass it explicitly through `SessionRunner -> RunExecutor -> EngineAdapter /
  TurnContext -> WaitToolkit`.

### WaitToolkit

- Add `AgentWaitService` and `ActiveDescendantWaitCondition` outside the
  Subagent Toolkit.
- Expose the model-visible `wait` tool with `timeout_seconds` in `[0, 600]` and
  concise prompt text.
- Wait algorithm is mailbox-first after startup: evaluate descendant
  eligibility, check all-kind pending mailbox state, subscribe/wait on observer
  revision with a one-second reconciliation interval, recheck mailbox before
  descendant state, and perform a final mailbox-first timeout check.
- Structured outcomes are `activity/mailbox`, `not_waitable/no_descendants`,
  `not_waitable/all_descendants_idle`, and `timed_out`.

## Implementation paths

- `python/apps/azents/src/azents/broker/types.py` and `broker/redis.py`: signal
  type, encoding, owner-targeted routing, stream decoding.
- Queue-only producer orchestration (`send_message` and terminal finalization):
  post-commit live-owner activity emission without any durable Session-state
  mutation or `SessionWakeUp`.
- `python/apps/azents/src/azents/worker/worker.py`: activity decode/routing
  before runner creation.
- `python/apps/azents/src/azents/worker/session/runner.py`: runner registry
  activity delivery, observer lifecycle, wakeup notification.
- `python/apps/azents/src/azents/worker/run/executor.py`, engine context and
  `TurnContext`: explicit observer injection.
- `python/apps/azents/src/azents/services/agent_wait.py` and
  `python/apps/azents/src/azents/engine/tools/wait.py`: shared wait service and
  independent toolkit/provider.
- `python/apps/azents/src/azents/engine/run/resolve.py` and worker dependency
  assembly: auto-bind the Wait Toolkit.
- `engine/tools/subagent.py` plus prompt/model fixtures: remove `wait_agent`,
  preserve concise subagent guidance, and retain all other collaboration tools.

## Transaction and activity semantics

Queue-only producers notify only after their mailbox transaction commits. Ordinary
`send_message` emits from its post-session-commit path. Terminal execution
results emit once at the `SessionRunner` terminal-result boundary after the
terminal lifecycle transaction has committed; lifecycle persistence helpers do
not emit a second signal. Truly out-of-band terminal transitions, such as
user-stop finalization without a returned run ID, emit explicitly after their
own committed transition. A notification failure is logged and does not roll
back durable admission. A live owner is identified by the existing lock plus
heartbeat; stale ownership is not a delivery target. The observer is
level-triggered by durable mailbox checks, so coalesced or lost signals are
covered by reconciliation.

## Verification plan

- Broker encoding/decoding, owner/no-owner routing, stale-heartbeat and
  owner-race tests; activity must never create a runner.
- Ordinary `send_message` and terminal result admissions notify an active owner
  only after commit; the same admissions leave an idle parent unstarted.
- Observer monotonic revisions, coalescing, close/cancellation, handover, and
  wakeup-vs-activity behavior.
- Explicit observer injection through runner/executor/engine/TurnContext.
- WaitToolkit schema, prompt snapshots, all five mailbox kinds, no descendants,
  all descendants idle, timeout, startup race, final timeout recheck, and
  lost-signal reconciliation.
- Active parent plus queue-only terminal/send activity ends wait; idle parent
  receives no wake and remains idle.
- Full Ruff, format, Pyright, targeted tests, full backend pytest, docs index
  check, and reviewer recheck by exact `/root/mailbox-reviewer` with a CLEAN
  verdict.

## Non-goals

No public API/client changes, mailbox schema changes, terminal-delivery repair
path restoration, scheduler wake semantics changes, or compatibility aliases.
