---
title: "Session Auto-Archive"
created: 2026-07-26
tags: [session, agent, lifecycle, scheduler]
document_role: primary
document_type: adr
snapshot_id: session-260726
---

# Session Auto-Archive

- Snapshot: [`session-260726/REQ`](../requirements/session-260726-auto-archive.md)
- Document reference: `session-260726/ADR`

## Context

Active session lists currently require manual archive. The existing archive
transition is a root-tree lifecycle operation: it validates eligibility, changes
the archive state, snapshots archive-retention policy, schedules purge work, and
performs post-commit cleanup. The automatic path must not diverge from that
transition.

## Decision Backlog

- [accepted] Persist the Agent-level inactivity TTL and root-session pin state.
- [accepted] Define a canonical activity clock independent of incidental row
  updates.
- [accepted] Run bounded automatic archive scans with transaction-time
  revalidation.
- [accepted] Share one archive transition between manual and automatic callers.
- [accepted] Expose the setting and pin state through the public API and web UI.

## Decisions

### D1. Store a required positive TTL on Agent and pin state on root Sessions

**Affected requirements:** `session-260726/REQ-1`,
`session-260726/REQ-4`, `session-260726/REQ-5`

`agents.auto_archive_ttl_days` is a non-null positive integer with a database
and application default of 30. `agent_sessions.pinned` is a non-null boolean
defaulting to false and is meaningful only on root sessions.

The schema migration backfills existing Agents to 30 days and existing Sessions
to unpinned. The API always exposes the effective Agent TTL; there is no
disablement sentinel in this snapshot.

**Rationale:** a required value makes the requested default effective for both
new and pre-existing Agents. A root-session flag matches the session-list
resource and avoids independently pinning hidden tree descendants.

**Rejected alternatives**

- Nullable TTL with `null` meaning disabled: adds an unrequested product
  policy and makes the default less reliable.
- A separate pin table: adds identity and lifecycle complexity for a
  one-to-one root-session property.

### D2. Maintain an explicit root-tree activity timestamp

**Affected requirements:** `session-260726/REQ-2`

`agent_sessions.last_activity_at` is a non-null timestamp on every Session.
It is advanced only for user messages, Agent messages, and tool executions.
Session creation initializes it to the creation time. During automatic archive
eligibility, the locked root tree's effective activity time is the maximum of
its members' `last_activity_at` values.

The migration conservatively seeds each Session from the best available
historical activity timestamp. Future eligibility relies only on the explicit
field.

**Rationale:** `updated_at` is affected by title, lifecycle, and pin changes;
using it would silently postpone archive for non-activity mutations. Computing
tree activity under the existing archive lock protects useful subagent work
without introducing child-to-root activity writes that could invert lifecycle
lock ordering.

**Rejected alternative**

- Deriving activity by repeatedly scanning event and tool records: makes
  scheduler scans expensive and leaves ambiguous ordering across event sources.

### D3. Use a bounded periodic scheduler scan with lock-and-recheck semantics

**Affected requirements:** `session-260726/REQ-2`,
`session-260726/REQ-5`

A scheduler-owned service runs in bounded batches. It finds active, non-primary,
non-pinned root Sessions whose `last_activity_at` is at or before the owning
Agent's TTL cutoff. Before transition, the shared archive service locks the
root tree and rechecks status, pin state, activity cutoff, primary status, and
run eligibility in the same transaction.

Concurrent scheduler attempts therefore reduce to one successful transition;
later contenders observe the changed state and skip it. Transient failures are
reported to the scheduled-task retry policy and retried in a later batch.

**Rationale:** a periodic scan is sufficient for TTL semantics and follows the
existing scheduler model. Rechecking under the archive lock protects against
new activity, pinning, and manual archive racing candidate discovery.

### D4. Extract and reuse one archive transition service

**Affected requirements:** `session-260726/REQ-3`

Manual archive retains its authorization boundary in Chat service, but delegates
the transaction, lifecycle orchestration, archive-retention snapshot, purge-job
scheduling, and post-commit cleanup to a shared Session archive service.
Automatic archive calls that same service after its system-owned eligibility
check.

**Rationale:** shared transition ownership is the only dependable way to keep
manual and automatic archive behavior identical as lifecycle participants
evolve.

**Rejected alternative**

- Reimplementing archive inside the scheduler: would duplicate retention,
  cleanup, and participant behavior and create drift.

### D5. Extend the existing Agent CRUD and session-sidebar contracts

**Affected requirements:** `session-260726/REQ-1`,
`session-260726/REQ-4`

The public Agent representation and partial-update request include
`auto_archive_ttl_days`. The public session representation includes `pinned`.
The Agent settings form edits the TTL. The session sidebar adds Pin/Unpin to the
existing overflow menu, shows a pin icon, and invalidates the existing session
list query after mutation.

**Rationale:** this reuses the existing ownership and authorization contracts
instead of creating a second settings or session-menu surface.

## Risks

- Historic activity data cannot perfectly distinguish tool activity from
  incidental updates before this feature. The migration seeds a conservative
  timestamp; new activity is exact after deployment.
- The periodic scan is eventually consistent. A session can remain visible
  until the next scheduler interval after its TTL elapses.
