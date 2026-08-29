---
title: "Discord Quiet Work Presence Decisions"
created: 2026-08-28
tags: [architecture, discord, external-channel, activity, lifecycle]
document_role: primary
document_type: adr
snapshot_id: discord-260828
---

# discord-260828/ADR: Discord Quiet Work Presence

- Snapshot: `discord-260828`
- Document reference: `discord-260828/ADR`
- Requirements:
  [`discord-260828/REQ`](../requirements/discord-260828-quiet-work-presence.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

Discord conversational Channel Work currently creates one retained Activity Tracker
whenever a new Work cycle receives its first canonical mailbox input. The Tracker
projection is independent from the inbound invocation classifier, so an unmentioned
message admitted by an existing all-messages Binding receives the same visible Tracker
as an explicit mention. Later `channel_action` progress changes can also create a
missing Tracker from the latest canonical desired progress.

Discord message normalization already retains whether the exact admitted trigger is an
eligible direct or managed-Bot-role invocation. Channel Work and its provider
projection are retained in binding-specific PostgreSQL-backed Toolkit State, while one
lease-fenced long-lived `discord.py` Client per connection is owned by the dedicated
External Channel Gateway runtime. The pinned SDK exposes `Messageable.typing()` as an
awaitable ten-second indicator and as an asynchronous context manager with internal
refresh.

The confirmed Requirements make typing desired for every active conversational Discord
Work, make Tracker visibility sticky after the first eligible mention in that Work
cycle, require restart recovery from durable Work authority, and leave Slack and
Scheduled Task presentation unchanged.

## Fixed and Derived Outcomes

- Existing Discord message admission, response modes, routing, authorization, Binding,
  Session, and Work-creation conditions remain unchanged.
- PostgreSQL-backed Channel Work is the sole durable authority for whether typing is
  desired and whether the current Work cycle is Tracker-visible.
- Tracker visibility is cycle-scoped and monotonic: a hidden active cycle may become
  visible after a qualifying mention and does not become hidden again before the cycle
  finishes.
- Tracker visibility must gate initial projection and every later `channel_action`
  progress create or update; gating only the initial Tracker is insufficient.
- A late qualifying mention publishes the latest complete desired progress snapshot
  through the existing retained-Tracker lifecycle.
- Canonical Work finish, ignore, Binding termination, or unavailable connection
  authority stops further typing renewal regardless of final provider reply outcome.
- Typing is a best-effort Discord presentation effect and never becomes input,
  execution, delivery, retry, or recovery authority.
- Discord exposes no explicit typing-stop operation; stopping renewal cannot guarantee
  zero residual provider display time.
- Slack and Scheduled Task Activity Tracker behavior remains unchanged.
- Redis and process-local state may wake or accelerate presentation but cannot be
  required for correctness or restart recovery.

## Material Decision Map

| ID | State | Decision |
| --- | --- | --- |
| `discord-260828/ADR-D1` | Accepted | The existing lease-fenced Discord Gateway connection owner owns sustained typing |
| `discord-260828/ADR-D2` | Accepted | Grandfather Work cycles present at rollout as Tracker-visible |

## Agent-Owned Implementation Categories

The Design may choose equivalent local details without additional requester decisions:

- typed field and helper names inside the existing Channel Work state;
- the exact bounded reconciliation, refresh, retry, and backoff intervals;
- use of the SDK awaitable typing form or a managed wrapper around the same public SDK
  capability, provided failures remain observable;
- task-registry, cancellation, and reference-count helper structure;
- repository query composition and indexes justified by the selected lifecycle;
- deterministic fake, fixture, and unit-test organization;
- structured metric and log field names that expose no content or credentials; and
- code-file and dependency-injection boundaries inside the approved runtime owner.

These choices cannot add another durable authority, require Redis for correctness,
change admission or response modes, expose hidden Trackers through progress updates,
apply mention gating to Slack or Scheduled Tasks, or make typing failure affect Work
correctness.

## Accepted Decisions

### discord-260828/ADR-D1 — The existing Discord Gateway connection owner owns sustained typing

Affected requirements: `discord-260828/REQ-1`, `discord-260828/REQ-2`,
`discord-260828/REQ-5`, and `discord-260828/REQ-6`.

The lease-fenced owner of each long-lived Discord Gateway connection also owns the
process-local typing tasks for that connection's current Discord delivery targets.
It reconciles those tasks from PostgreSQL-backed active Channel Work while the current
connection lease and SDK Client remain valid. Gateway startup, reconnect, lease
acquisition, and periodic reconciliation restore typing for still-active Work;
canonical finish, ignore, Binding termination, authority loss, and shutdown cancel the
corresponding local tasks.

This keeps one authenticated persistent SDK lifecycle and one fenced owner per
customer-owned Discord App. Typing remains a presentation responsibility inside the
provider Gateway runtime and does not become Gateway transport authority, durable
state, or a dependency of event admission. The Gateway owner may use an immediate
best-effort wake or pulse to reduce startup latency, but PostgreSQL reconciliation is
the restart and missed-signal authority.

Rejected alternatives:

- A separate persistent typing runtime would require another authenticated SDK Client
  lifecycle, ownership fence, deployment unit, health contract, shutdown path, and
  recovery loop for the same Bot credential without creating independent product
  value.
- Agent Worker ownership would couple typing to one run process even though Channel
  Work may remain active across runs, idle continuation, and Agent Worker restart.

### discord-260828/ADR-D2 — Existing Work cycles remain Tracker-visible across rollout

Affected requirements: `discord-260828/REQ-3`, `discord-260828/REQ-4`, and
`discord-260828/REQ-5`.

Every Channel Work state that exists when the new state schema is deployed is migrated
as Tracker-visible. Any retained Tracker identity and projection observation remains
unchanged, no provider delete is planned, and active Discord Work becomes eligible for
typing reconciliation. Mention-gated hidden state applies only when a new Work cycle is
created after the new behavior is active.

This treats the brief deployment transition as compatibility rather than attempting to
reinterpret historical input. The migration is the complete compatibility boundary;
runtime code reads only the new required Work-state shape and does not preserve a
missing-field fallback.

Rejected alternatives:

- Reconstruct mention history from Session events, mailbox history, or transcript
  content. Those records are not the existing Work cycle's visibility authority and
  may have crossed compaction, deletion, or asynchronous admission boundaries.
- Mark existing Work hidden when it has no retained provider message. A missing
  projection may represent a failed or ambiguous create rather than an unmentioned
  cycle, so this would silently change existing behavior.
- Delete existing Trackers during deployment. This creates an unsolicited provider
  mutation and visible message removal for a short-lived compatibility window.

## Risks and Consequences

- Discord Gateway outages necessarily create a temporary typing gap; recovery can
  restore only currently active Work after the provider connection returns.
- Work and Gateway lifecycle transitions are independent transactions, so presentation
  must converge through durable reconciliation rather than assume one process-local
  callback observes every transition.
- Existing Toolkit State requires one forward schema transition. The accepted rollout
  decision determines the migrated Tracker-visibility value for pre-deployment cycles.
- Discord may retain the final indicator until its provider expiry even after Azents
  stops renewal.
