---
title: "Reliable External Channel Execution Design"
created: 2026-08-01
updated: 2026-08-01
implemented: 2026-08-01
tags: [external-channel, ingress, mailbox, session, backend, frontend, testenv]
document_role: primary
document_type: design
snapshot_id: ingress-260801
---

# Reliable External Channel Execution Design

- Snapshot: `ingress-260801`
- Document reference: `ingress-260801/DESIGN`
- Requirements:
  [`ingress-260801/REQ`](../requirements/ingress-260801-reliable-external-channel-execution.md)
- Decisions:
  [`ingress-260801/ADR`](../adr/ingress-260801-reliable-external-channel-execution.md)

## Architecture

### Atomic acceptance

The ingestion store locks and revalidates connection, resource, route, binding, access,
and conversation-position authority. One short transaction then creates or reuses:

- the real root AgentSession and binding;
- initial Channel Work;
- Session-link and initial-progress delivery intents;
- the deterministic canonical mailbox input;
- the Session running transition; and
- the conversation-position advance.

The cursor compare-and-set restarts bounded history preparation when another accepted
trigger advanced the same conversation. Mailbox idempotency converges duplicate
callbacks and replay onto the same Session input.

After commit, the wake dispatcher verifies that the mailbox item still belongs to the
Session and sends a routing-only `SessionWakeUp`. If the item was already promoted, the
duplicate wake is an idempotent no-op. Broker unavailability remains retryable while
the item is pending.

This implements `ingress-260801/REQ-1` and `ingress-260801/REQ-2` through
`ingress-260801/ADR-D1`.

### Independent provider controls

Initial provider controls are ordinary durable delivery attempts. Ingestion may return
one pending control identity for immediate transport-owned settlement, while the
provider-control worker lists and attempts every remaining pending control.

Delivery start and settlement retain their existing locks and current authority
revalidation. No query joins delivery attempts to activation state, and no delivery
outcome changes mailbox promotability.

This implements `ingress-260801/REQ-3` through `ingress-260801/ADR-D2`.

### Existing-data migration

Before dropping activation state, the migration:

1. joins activation rows to retained mailbox items;
2. advances each owning conversation position to the greatest retained trigger when it
   is newer than the current cursor;
3. marks each active owning Session running; and
4. removes activation delivery links, activation rows, the binding composite
   constraint used only by activation, and the activation enum.

The downgrade recreates the schema shape but cannot reconstruct removed historical
activation rows.

This implements `ingress-260801/REQ-4` through `ingress-260801/ADR-D3`.

### Session-creation telemetry

Both automatic binding creation and approved-access binding creation retain the
`created` result from the root Session creation service. The informational log is
emitted only after the owning transaction commits. It contains:

- `external_channel_provider`;
- `provider_event_type`, restricted to `app_mention`, `message`,
  `discord_message_create`, or `unknown`.

No log is emitted for rollback, Session reuse, or an idempotent retry.

This implements `ingress-260801/REQ-5`.

### Shared pending projection

`pendingMessageProjection.ts` maps pending mailbox items and pending input buffers into
the existing `ChatMessage` union. `PendingMailboxBubble`,
`PendingInputBufferBubble`, and `OptimisticInputBubble` delegate content rendering to
`MessageBubble`.

`MessageBubble` accepts an explicit opacity and optional additional actions. It places
pending deletion actions in the same metadata/action surface used by promoted
messages. `ExternalChannelMessage` accepts the same action surface instead of requiring
pending-only markup.

This implements `ingress-260801/REQ-6` through `ingress-260801/ADR-D4`.

## Failure and Recovery

- Position mismatch rolls back acceptance and restarts bounded provider-history
  preparation.
- Provider-history, coordination, or broker failure returns a retryable ingress
  outcome.
- Provider-control failure remains terminal evidence for that mutation attempt but does
  not alter the accepted mailbox path.
- Duplicate ingress recovers the pending wake while the mailbox item exists and becomes
  a no-op after promotion.
- Access Allow commits its decision and binding before replay; replay failure never
  reverts the authorization decision.

## Removal and Replacement

| Obsolete surface | Replacement or remaining authority | Removal verification |
| --- | --- | --- |
| Session activation enum, models, tables, delivery links, constraints | Conversation position, mailbox item, Session run state, delivery ledger | Migration test and removed-symbol search |
| Admission/stage/activate/block protocol | One atomic `accept` transaction plus post-commit wake | Ingestion and mailbox-store tests |
| Activation-aware mailbox promotability checks | Ordinary FIFO mailbox semantics | Mailbox service tests |
| Activation-aware provider-control ordering and rejection | Existing delivery attempt ordering, locking, and authority checks | Work repository and provider-control tests |
| Required-delivery deadline and terminal activation reasons | Independent delivery outcome evidence | Ingestion regression tests |
| Pending per-message-type markup | `ChatMessage` projection and `MessageBubble` | Frontend lint, typecheck, Storybook, and visual stories |
| Stale current-behavior activation text | Updated Living Specs | Spec audit and `last_verified_at` updates |

Historical implemented Requirements, accepted ADRs, and Designs are retained unchanged.
Temporary implementation plans are not part of this snapshot.

## Test Strategy

### Primary E2E matrix

- Slack HTTP unknown-participant approval and replay reaches one Session execution.
- Slack Socket Mode duplicate/recovery preserves route and one accepted mailbox input.
- Discord signed interaction creates and executes the bound Session.
- Discord Gateway message creation provisions, binds, wakes, and executes.
- Multi-App selector journeys converge without duplicate Session input.

The deterministic lane uses public APIs and provider fakes. It must not write product
database state directly. Live External Channel and runtime-provider lanes remain
separately selected optional environments.

### Focused verification

- Migration upgrade releases a blocked retained mailbox input, advances its cursor,
  marks its Session running, removes activation schema, and validates downgrade shape.
- Ingestion tests prove provider-control failure or cancellation cannot block wake.
- Creation-log tests prove allowlisted fields, commit ordering, and idempotent silence.
- Mailbox tests prove External Channel items use ordinary FIFO promotion.
- Frontend checks cover type projection, shared rendering, deletion actions, and
  Storybook builds.

### Evidence and CI

- Retain exact test commands and pass counts in the pull-request report.
- Backend full suite, migration suite, frontend lint/typecheck/build, Storybook, and
  deterministic E2E must pass locally or in required CI as applicable.
- The latest pull-request head must pass every required check before completion is
  reported.
- Optional live tests may skip only when their documented external credentials or
  prerequisite snapshot is unavailable; deterministic provider-fake coverage may not
  skip.
