---
title: "Unified Agent Input Mailbox"
created: 2026-07-26
tags: [agent, mailbox, engine, architecture]
document_role: primary
document_type: adr
snapshot_id: mailbox-260726
---

# Unified Agent Input Mailbox

- Snapshot: `mailbox-260726`
- Document reference: `mailbox-260726/ADR`
- Requirements: [Unified Agent Input Mailbox Requirements](../requirements/mailbox-260726-unified-agent-input-mailbox.md) (`mailbox-260726/REQ`)

## Context

The confirmed Requirements establish one canonical consume-on-read mailbox for AgentSession-targeted messages and Turn Actions, a common pending UI lifecycle, and a generalized model-visible `wait` tool. The current repository already has a shared `input_buffers` FIFO, but its ownership and projections remain coupled to producer-specific behavior:

- `InputBufferService` stores and prepares `USER_MESSAGE`, `GOAL_CONTINUATION`, `ACTION_MESSAGE`, `AGENT_MESSAGE`, and `EXTERNAL_CHANNEL_INVOCATION`.
- `ACTION_MESSAGE` includes both producing Goal/Skill actions and operation Turn Actions that hand off to `action_execution`.
- External Channel invocation buffers store a batch reference and re-read provider-domain projection records during promotion.
- `wait_agent` polls only pending `AGENT_MESSAGE` rows and performs subagent terminal-delivery repair while waiting.
- scheduler `SessionWakeUp` messages are payload-free consuming control signals and are not delivered to a tool executing inside the active Run.
- pending Web projection is not uniform across input kinds, and External Channel invocation has no pending live projection.

The mailbox is a passive persistence and consumption boundary. It does not publish broker messages, mutate Session scheduling state, or emit activity notifications. A producer confirms durable mailbox admission and then performs the Session wakeup or non-scheduling activity notification required by its own scheduling contract. A Session wakeup is the complete operation of ensuring durable running state and sending the broker signal after commit; a transient activity notification is not called a wakeup.

Relevant current implementation evidence includes:

- `python/apps/azents/src/azents/core/enums.py`
- `python/apps/azents/src/azents/services/input_buffer.py`
- `python/apps/azents/src/azents/services/agent_mailbox.py`
- `python/apps/azents/src/azents/services/subagent_terminal_result.py`
- `python/apps/azents/src/azents/engine/tools/subagent.py`
- `python/apps/azents/src/azents/services/chat/live_events.py`
- `python/apps/azents/src/azents/services/external_channel/`
- `python/apps/azents/src/azents/worker/session/`

## Requirements Boundaries

The following product contracts are fixed by `mailbox-260726/REQ` and are not reopened by this ADR:

- mailbox admission begins after target Session and delivery eligibility resolution;
- messages and Turn Actions share one ordered mailbox;
- mailbox persistence has no wake side effects, and producers own post-admission Session wakeup or non-scheduling activity behavior;
- mailbox observation is non-consuming, while successful input processing consumes the item;
- operation Turn Actions leave the mailbox only after safe action-execution handoff;
- pending mailbox items have source-specific reduced-emphasis Web presentation;
- `wait` retains the existing active-descendant eligibility and timeout contract;
- every pending mailbox item can end an eligible wait; and
- arbitrary tool interruption remains out of scope.

## Decision Backlog

The decisions below must be resolved in order unless an accepted decision changes their dependency.

### Decision Point 1: Canonical mailbox persistence and migration

**Status**: Accepted as `mailbox-260726/ADR-D1`

Evolve the current `input_buffers` persistence in place into the canonical mailbox. Rename the durable model, table, repository, service, and related foreign-key vocabulary to `mailbox_items` and mailbox terminology while preserving existing row identity and FIFO order through migration. All producers must use the shared mailbox boundary after the transition. Do not introduce a parallel mailbox, dual-write period, compatibility alias, or producer-specific pending-delivery fallback.

Affected requirements: `mailbox-260726/REQ-1`, `mailbox-260726/REQ-3`.

**Rationale**

- The existing persistence already provides the Session FIFO, idempotency, row locking, promotion, retry, and operation-action handoff foundations required by the confirmed Requirements.
- An in-place transition establishes one explicit source of truth without creating cross-store ordering or deduplication problems.
- Renaming related references, including action-execution source identity, makes the mailbox boundary structural rather than a service-only facade over legacy terminology.

**Rejected alternatives**

- Add a new mailbox beside `input_buffers` and migrate producers gradually. This would create a period with two pending-input sources and require cross-store ordering, wait observation, UI projection, and recovery.
- Keep the physical `input_buffers` model and rename only the service layer. This would leave the legacy storage concept as the actual ownership boundary and would not make the unified mailbox explicit throughout the internal structure.

### Decision Point 2: Mailbox item granularity and correlation

**Status**: Accepted as `mailbox-260726/ADR-D2`

Use one durable mailbox row as an atomic delivery envelope. The envelope owns FIFO position, scheduling intent, wake observation, and consume-on-read behavior. Its typed immutable payload contains one or more ordered input presentation items with stable item keys. Ordinary user messages, Agent messages, Goal continuations, and Turn Actions normally contain one item. An External Channel invocation envelope contains the complete ordered snapshot of context and trigger messages admitted together.

Affected requirements: `mailbox-260726/REQ-1`, `mailbox-260726/REQ-2`, `mailbox-260726/REQ-3`.

External Channel context collection, authorization, routing, and batch construction occur entirely before mailbox admission. Unapproved or context-only messages remain owned by the External Channel domain. When an authorized invocation arrives, the External Channel domain combines the retained context and trigger into one finalized ordered snapshot and enqueues that snapshot once. After admission, mailbox promotion must not re-read the External Channel domain to reconstruct Agent input.

The admitted External Channel envelope retains `wake_session` scheduling intent. Its producer ensures the durable Session state is running in the admission workflow and sends the existing broker signal after commit so an idle target starts processing the envelope. Decision Point 3 determines how that signal also reaches an already-running Agent blocked in `wait` without requiring a duplicate notification. Mailbox persistence itself emits no signal, and pre-admission context collection performs neither wakeup nor activity notification.

Each embedded item carries a stable item key used to correlate its pending Web presentation with the durable event created during promotion. The envelope ID remains the source identity for operation Turn Action handoff to `action_execution`. One envelope may therefore create multiple durable events or transfer to an intermediate action execution without losing one logical input identity.

**Rationale**

- Envelope-level FIFO and consumption preserve atomic External Channel invocation context and prevent unrelated Session input from interleaving within one admitted batch.
- Copying the complete immutable input snapshot into the mailbox makes the mailbox the sole pending-delivery source of truth after admission.
- Embedded stable item keys provide per-message UI and durable-event correlation without adding a short-lived relational child table.
- The same envelope abstraction supports single-item messages, typed Turn Actions, multi-message External Channel invocations, and future admitted compound inputs.

**Rejected alternatives**

- Store each visible External Channel message as a separate mailbox row and recreate atomic batch claiming through group IDs and sequence locks. This would complicate FIFO, scheduling, and recovery.
- Normalize envelope children into a separate mailbox-item child table. The mailbox is consume-on-read and does not retain history, so the additional joins, locks, and cascade lifecycle are not justified.

### Decision Point 3: Mailbox activity notification

**Status**: Accepted as `mailbox-260726/ADR-D3`

Reuse the existing full Session-wakeup signal as mailbox activity when the target SessionRunner is already active. A `wake_session` producer owns the complete operation: admit the mailbox item, ensure durable Session running state, commit, and send one `SessionWakeUp`. The active runner must make that same signal observable to an eligible `wait`; the producer does not send a duplicate activity notification.

A `queue_only` producer does not ensure running state and does not send `SessionWakeUp`. After confirming mailbox admission, it sends a transient mailbox-activity notification only to an existing live Session owner. If no live owner exists, the notification is discarded and no runner is created. The notification carries no input payload and never becomes a pending scheduler message.

Signals are hints rather than the source of truth. An observer rechecks the durable mailbox after subscribing and after every signal. A bounded low-frequency reconciliation check covers a lost transient signal without returning to continuous 100-millisecond polling.

Affected requirements: `mailbox-260726/REQ-4`, `mailbox-260726/REQ-5`, `mailbox-260726/REQ-6`.

**Rationale**

- A full Session wakeup already reaches the active Session owner, so reusing it avoids duplicate signals for Session-waking input.
- A live-owner-only activity path lets queue-only Agent messages resume an existing wait without starting an idle Session or changing their scheduling semantics.
- Keeping signal payloads empty and re-reading the mailbox preserves the durable level-triggered source of truth.
- Separating full wakeup from transient activity keeps durable Session-state changes explicit and producer-owned.

**Rejected alternatives**

- Send a separate activity notification for every item in addition to full Session wakeup. This duplicates signals and introduces unnecessary ordering and partial-failure cases.
- Perform a full Session wakeup for queue-only input. This would change established `send_message` and terminal-result scheduling semantics.
- Detect queue-only mailbox activity only through continuous DB polling. This would retain polling latency and load instead of providing shared runtime activity notification.

### Decision Point 4: Runtime ownership and dependency boundary

**Status**: Accepted as `mailbox-260726/ADR-D4`

The `SessionRunner` owns one Run-scoped `MailboxActivityObserver` and exposes it to the active Engine Run through `TurnContext`. The observer provides a monotonic activity revision and a cancellable `wait_after(revision, timeout)` operation. It carries no mailbox payload and consumes no broker or mailbox item.

When the runner receives a full `SessionWakeUp` for its active Session, it preserves the existing scheduler inbox behavior and also advances the observer revision. A live-owner-only queue activity notification advances only the observer revision and does not enter the scheduler inbox. The generalized `wait` snapshots the observer revision, checks descendant eligibility and durable mailbox state, waits for a later revision or reconciliation interval, and rechecks the mailbox.

The observer lifecycle is bound to the active Run and is discarded when that Run ends. The existing Run supervisor, stop controller, and `check_stop` capability continue to own cancellation, shutdown, and interruption. Toolkits do not receive the raw `SessionRunnerInbox`, Redis connection, or Session ownership primitives.

Affected requirements: `mailbox-260726/REQ-3`, `mailbox-260726/REQ-5`.

**Rationale**

- `SessionRunner` already owns broker delivery, Session ownership, and Run lifecycle, so it is the correct boundary for converting runtime signals into non-consuming activity observations.
- A monotonic revision closes raw-event coalescing races and lets the tool distinguish activity that occurred after its snapshot.
- `TurnContext` provides a Run-scoped dependency boundary without exposing scheduler queues or requiring Toolkit-level Redis subscriptions.
- Keeping stop handling separate preserves the confirmed non-goal of interrupting arbitrary tools on mailbox activity.

**Rejected alternatives**

- Expose the runner inbox directly to the Toolkit. This would let the tool compete with scheduler and stop consumers.
- Let the Toolkit subscribe to Redis. This would duplicate ownership routing, subscription lifecycle, and recovery inside model-visible tool code.
- Use a worker-global observer registry. This would introduce mutable process-global lifecycle and stale entries across owner handoff.

### Decision Point 5: Terminal-result delivery and repair ownership

**Status**: Accepted as `mailbox-260726/ADR-D5`

Finalize an eligible child Run and enqueue its direct-parent terminal-result envelope in one database transaction. The transaction records the terminal projection, validates direct-parent delivery eligibility, creates the queue-only parent mailbox envelope, and records the final delivery state as enqueued or explicitly suppressed. An eligible terminal Run is not committed without its canonical parent mailbox delivery.

After commit, the terminal producer sends only the live-owner queue activity notification selected by `mailbox-260726/ADR-D3`. It does not ensure the parent Session is running and does not send `SessionWakeUp`. An already-running parent can expose the activity to an active `wait`, while an idle parent remains idle until later Session-waking input arrives. This applies to completed, failed, stopped, interrupted, and cancelled terminal-result messages. A failed transaction leaves the child Run recoverable so the entire terminal finalization can be retried.

The generalized `wait` is a pure observer. It does not inspect child terminal Run projections, create terminal messages, advance delivery cursors, or invoke terminal-result repair. Remove the current parent-wait repair path and any later source-Run repair path that exists only to compensate for non-atomic terminal delivery.

Affected requirements: `mailbox-260726/REQ-5`, `mailbox-260726/REQ-8`.

**Rationale**

- Atomic finalization makes the guarantee “an eligible completed descendant has a parent mailbox result” a database invariant rather than a wait-time repair behavior.
- A pure generalized wait remains reusable for user, External Channel, Agent, Goal, and Turn Action input without subagent-specific production side effects.
- Queue-only delivery preserves the current source-owned scheduling contract while the live-owner activity path lets an already-running parent resume from `wait`.

**Rejected alternatives**

- Commit terminal state plus a producer-specific durable delivery intent for later reconciliation. This would reintroduce a second pending-delivery source beside the canonical mailbox.
- Keep wait-triggered or later-source-Run repair. This would couple generalized mailbox observation to subagent-specific message creation and leave delivery timing dependent on later activity.
- Make terminal results perform a full parent Session wakeup. The current scheduling contract intentionally reserves full wakeup for new-task messages such as spawn assignments and follow-up tasks; ordinary messages and terminal results remain queue-only.

### Decision Point 6: `wait` tool surface and prompt contract

**Status**: Accepted as `mailbox-260726/ADR-D6`

Create an independent auto-bound `WaitToolkit` that owns the model-visible `wait` tool. A shared Agent wait service evaluates an injected wait condition, checks durable mailbox state, and waits through the Run-scoped mailbox activity observer. The only condition in this snapshot is active descendant work. Future conditions may extend the service without moving the tool or coupling generic wait infrastructure to the Subagent Toolkit.

Remove the model-visible `wait_agent` name without an alias. Preserve the optional `timeout_seconds` input with a 30-second default and an inclusive range of 0 through 600 seconds. Return structured outcomes without mailbox payload:

- `{\"outcome\":\"activity\",\"reason\":\"mailbox\"}`
- `{\"outcome\":\"not_waitable\",\"reason\":\"no_descendants\"}`
- `{\"outcome\":\"not_waitable\",\"reason\":\"all_descendants_idle\"}`
- `{\"outcome\":\"timed_out\"}`

Use this concise tool description:

> Wait while descendant work is active. Returns when any mailbox item arrives, no descendants exist, all descendants are idle, or the timeout expires. This tool does not consume mailbox items. Default timeout: 30 seconds. Maximum: 600 seconds. Do not use this tool only to wait for future user or External Channel input.

Update every Subagent model-visible prompt surface:

- root usage hint: `Use wait only while descendant work is active. Any mailbox item may end the wait.`
- child usage hint: `Use wait only for descendants you created, not to wait for parent instructions.`
- shared direct-tool hint: replace `wait_agent` with `wait`;
- forked-history reminder: `Use wait only for descendants you created.`;
- terminal-result hint: `Your final response is queued in your parent's mailbox. It can end an active wait but does not wake an idle parent.`

Keep the prompt concise and do not duplicate the full tool description in every Subagent hint.

Affected requirements: `mailbox-260726/REQ-4`, `mailbox-260726/REQ-5`, `mailbox-260726/REQ-6`, `mailbox-260726/REQ-7`.

**Rationale**

- Tool ownership remains stable when later wait conditions are introduced.
- The current descendant-only rule remains explicit without making Subagent Toolkit own generic waiting.
- Structured outcomes avoid model parsing of prose while keeping mailbox content on the normal input path.
- Short, complementary prompt fragments reduce repetition and misuse.

**Rejected alternatives**

- Keep `wait` in Subagent Toolkit. This would make future conditions depend on or relocate a domain-specific tool.
- Put `wait` in Mailbox Toolkit. Mailbox activity is a wake source, not the owner of wait eligibility.
- Use a broad Agent-loop Toolkit. A dedicated Wait Toolkit is the narrower current responsibility.
- Retain long duplicated wait instructions across every Subagent prompt surface.

### Decision Point 7: Web pending projection and API contract

**Status**: Accepted as `mailbox-260726/ADR-D7`

The server owns a typed pending mailbox projection for REST live-state reads and WebSocket actions. Each projected envelope item includes its mailbox envelope ID, stable item key, semantic kind, creation time, source-specific presentation payload, and pending state. The frontend selects its existing message or action renderer from the semantic kind and applies the common reduced-emphasis pending presentation.

Durable events and action-execution projections retain correlation to the same mailbox envelope and item key. During a transition, the server publishes or returns the durable event or active action execution before removing the pending mailbox projection. On REST resync, durable history or active action ownership wins over a stale pending projection with the same correlation identity.

Do not expose raw mailbox persistence rows or require the frontend to decode storage payloads. Do not represent pending mailbox items as ordinary durable `Event` records with metadata flags. The public projection is a distinct typed view over the mailbox envelope and its embedded items.

Affected requirements: `mailbox-260726/REQ-2`, `mailbox-260726/REQ-3`.

**Rationale**

- A server-owned projection keeps mailbox schema private while providing one contract for every input kind.
- Stable envelope and item correlation supports compound External Channel input and operation Turn Action handoff.
- Durable-before-pending-removal ordering avoids visible gaps, duplicates, and reorder during live transitions.
- REST reconstruction from durable mailbox state makes refresh and reconnect independent of optimistic client state.

**Rejected alternatives**

- Convert every pending mailbox item into a temporary Event. This would blur pending delivery state with durable transcript history.
- Expose raw mailbox payloads to the frontend. This would couple public UI behavior to persistence schema and duplicate kind-specific decoding.

## Accepted Decisions

### `mailbox-260726/ADR-D1`: Evolve `input_buffers` in place into the canonical mailbox

Preserve existing durable identities and FIFO semantics while renaming and evolving the current persistence into `mailbox_items`. Replace producer-specific pending-delivery access with the shared mailbox service, and do not retain a parallel store, dual-write path, or compatibility alias.

### `mailbox-260726/ADR-D2`: Store one atomic envelope with complete typed input snapshots

Use one mailbox row as the FIFO, scheduling, wake, and consumption unit. Store complete immutable input presentation items inside its typed payload with stable item keys. External Channel authorization and batching finish before one finalized context-plus-trigger envelope enters the mailbox; promotion does not reconstruct the input from External Channel storage.

The finalized External Channel envelope is admitted with Session-waking intent. The External Channel producer ensures durable running state and emits one post-commit broker signal, which must also make the mailbox change observable to an active `wait`. Mailbox persistence and pre-admission context-only storage perform neither wakeup nor activity notification.

### `mailbox-260726/ADR-D3`: Reuse full wakeup and add live-owner-only queue activity

Session-waking producers ensure durable running state and send one existing `SessionWakeUp`, which an active runner also exposes as mailbox activity. Queue-only producers send only a transient live-owner activity notification after admission; it never starts an idle Session. Observers treat both signals as hints and re-read durable mailbox state.

### `mailbox-260726/ADR-D4`: Use a SessionRunner-owned Run-scoped activity observer

`SessionRunner` translates full wakeups and queue-only activity notifications into a monotonic `MailboxActivityObserver` revision exposed through `TurnContext`. Toolkits wait on that capability and re-read durable mailbox state without consuming the scheduler inbox, broker messages, or mailbox items.

### `mailbox-260726/ADR-D5`: Atomically finalize child Runs with parent mailbox delivery

For an eligible child terminal result, commit the terminal Run projection, direct-parent queue-only mailbox envelope, and final delivery state in one transaction. Send only a live-owner activity notification after commit; do not ensure the parent running state or send `SessionWakeUp`. Generalized `wait` remains a pure observer and no longer performs terminal-delivery repair.

### `mailbox-260726/ADR-D6`: Expose concise `wait` through an independent Wait Toolkit

Replace `wait_agent` with an independent auto-bound `wait` tool backed by an extensible condition service. The initial condition is active descendant work. Use structured outcome/reason results, the existing 30-to-600-second timeout contract, and concise complementary Wait and Subagent prompt guidance.

### `mailbox-260726/ADR-D7`: Serve typed pending mailbox projections from the backend

Expose a distinct server-owned pending mailbox projection with stable envelope and item correlation. Reuse source-specific frontend renderers with common pending emphasis, publish durable or active ownership before pending removal, and keep raw mailbox persistence private.
