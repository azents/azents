---
title: "Batched External Channel Conversation Ingress Decisions"
created: 2026-08-10
tags: [architecture, external-channel, reliability, messaging, runtime]
document_role: primary
document_type: adr
snapshot_id: channel-260810
---

# channel-260810/ADR: Batched External Channel Conversation Ingress

- Snapshot: `channel-260810`
- Document reference: `channel-260810/ADR`
- Requirements:
  [`channel-260810/REQ`](../requirements/channel-260810-batched-conversation-ingress.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

The confirmed Requirements separate short provider callback admission from durable,
provider-history-backed message resolution. Every admitted trigger is Session-bound and
content-free at durable receipt. Backlog processing preserves durable ingress order,
creates one mailbox item per canonical provider message, commits the successful subset
together, and issues one recoverable Session wake after the processing batch.

The current implementation performs provider history work before durable trigger
receipt and embeds several canonical provider messages inside one External Channel
mailbox envelope. The canonical message and chat projections also name prompt
presentation metadata `authorization` with `context_only` and
`authorized_invocation` values. The new Requirements replace those contracts rather
than extending them.

The current Scheduler already separates durable scheduling state from local handler
execution. Production runs a separate Scheduler Deployment while devserver co-locates
the Scheduler service. Each Scheduler instance uses local direct execution; PostgreSQL
conditional claiming on `scheduled_task_states` provides distributed safety and
at-least-once reclaim after lease expiry. The accepted `periodic-260620/ADR` rejected
Temporal for Scheduler v1 while retaining it as a future executor candidate. No live
Temporal client, worker, or deployment is currently wired.

## Fixed and Derived Outcomes

These outcomes are determined by `channel-260810/REQ`, existing accepted authority, or
project constraints and are not open ADR choices:

- Callback admission authenticates and filters mention/response mode, participant
  access, Binding, and target Session before one Session-bound ingress trigger is
  durably inserted.
- PostgreSQL domain state owns active ingress durability, queue order, idempotency,
  retry state, and recovery. Successful admission, cursor suppression, and bounded
  failure remove the completed queue row; bounded failure emits one sanitized
  structured log. Redis or another broker may reduce latency but cannot own
  correctness.
- Provider history remains canonical content authority, and adopted provider SDK public
  APIs remain authoritative where they support the required operation.
- One Session has at most one active processing batch. The first batch after idle
  contains one trigger; later backlog batches contain at most ten and preserve durable
  queue order rather than provider-position order.
- Same-conversation items observe cursor advancement between queue items in one batch.
  Cursor-covered processing attempts are suppressed without erasing an invocation
  prompt role already materialized through correlated history.
- Every canonical provider message has an independent mailbox item and FIFO identity.
  Successful items from one processing batch are admitted atomically; retryable and
  terminal ingress items create none; one recoverable wake follows a non-empty commit.
- Existing mailbox pending state remains the durable evidence that an idle Session must
  be woken. A second durable wake authority is not introduced.
- The canonical message field is `prompt_role = context | invocation`. Legacy names are
  removed without aliases, dual reads, compatibility payloads, or fallback rendering.
- Existing persisted External Channel mailbox and event JSON must be transformed to the
  canonical contract during deployment. Pending multi-message envelopes must be split
  into independently ordered mailbox items rather than retained behind a legacy reader.
- Input arriving during an already active model call remains outside this snapshot.

## Material Decision Map

| ID | State | Decision |
| --- | --- | --- |
| `channel-260810/ADR-D1` | Accepted | Initial local Job Runtime boundary, producer topology, and Scheduler integration scope |
| `channel-260810/ADR-D2` | Accepted | Future Temporal adoption unit and permitted local/Temporal coexistence |

D1 and D2 were confirmed by the requester after review against this complete decision
map. The revised Requirements directly fix completed-outcome removal and failure-only
logging, so retention is no longer an ADR choice.

## Agent-Owned Implementation Categories

The Design may choose equivalent local details without additional requester decisions:

- repository, table, column, model, handler, and metric identifiers;
- bounded in-memory queue and semaphore implementation;
- transaction helper, query, and lock composition that preserves the accepted
  authority and lifecycle;
- deterministic idempotency-key encoding and local correlation indexes;
- migration SQL structure that performs the required canonical rewrite without a
  compatibility reader;
- fixture names, test helper boundaries, and equivalent module layout; and
- structured-log field names that expose only approved sanitized diagnostics.

These categories cannot introduce another durable authority, runtime mode, fallback,
compatibility contract, or product behavior.

## Accepted Decisions

### channel-260810/ADR-D1 — Share one producer-local Job Runtime across External Channel and Scheduler

The initial Job Runtime is one common supervised, bounded in-process execution
substrate used by External Channel ingress and Scheduler handlers.

Every long-lived producer process that submits registered background work hosts one
Local Job Runtime replica. External Channel producers request local execution only
after their Session-bound durable ingress transaction commits. The Scheduler delegates
claimed task handler execution to the same runtime contract while retaining ownership
of due discovery, `scheduled_task_states`, PostgreSQL leases, retry scheduling, and
current task state.

The Local Job Runtime owns only registered-handler dispatch, bounded concurrency,
deadlines, cancellation, structured outcomes, and graceful shutdown. It does not own a
generic PostgreSQL execution queue, durable retry schedule, attempt history,
cross-process transport, or central Background Worker fleet. Lost local execution is
recovered from each domain's durable state.

Standalone devserver hosts one Local Job Runtime in its all-in-one process. Distributed
mode hosts the same runtime inside each long-lived producer process; it does not add a
separate execution Deployment for this backend.

Affected requirements: `channel-260810/REQ-2`, `channel-260810/REQ-3`,
`channel-260810/REQ-6`, and `channel-260810/REQ-8`.

Rejected alternatives:

- Limit the common runtime to External Channel while leaving Scheduler handler
  execution behind a second local executor abstraction. This reduces the first diff but
  duplicates deadline, cancellation, concurrency, shutdown, and future-backend
  boundaries.
- Introduce a central custom PostgreSQL job queue and Background Worker fleet. This
  would duplicate durable domain authority and grow a custom workflow backend beneath
  any future Temporal integration.
- Adopt Temporal in the initial implementation. The current lightweight handlers and
  standalone devserver do not justify making Temporal an immediate runtime dependency.

### channel-260810/ADR-D2 — Select one configured distributed Job Runtime backend for all registered handlers

Distributed deployments select one common Job Runtime backend through system
configuration: `local` or `temporal`. The selected backend applies to every registered
background handler, including External Channel ingress and Scheduler task execution.
One deployment does not route individual handlers or domains to different backends.

The standalone devserver remains able to select the Local Job Runtime without requiring
Temporal. When a future snapshot adopts the Temporal backend, Temporal owns distributed
execution queues, retries, timers, cancellation, execution history, and worker
dispatch. Domain tables continue to own business intent and canonical domain state.

A transactional outbox may recover handoff from a committed domain transaction to
Temporal, but it is transport evidence rather than a second handler-execution queue.
The future Temporal migration must move the complete registered-handler backend
coherently instead of retaining per-handler Local/Temporal routing.

Affected requirements: `channel-260810/REQ-2`, `channel-260810/REQ-3`,
`channel-260810/REQ-6`, and `channel-260810/REQ-8`.

Rejected alternatives:

- Configure Local or Temporal independently per handler or domain. This creates a
  permanent routing surface and concurrent retry, cancellation, observability, and
  operational models.
- Hard-code the backend by deployment mode. Backend ownership is an explicit system
  configuration choice; distributed packaging alone does not silently select it.
- Retain a custom PostgreSQL handler queue beneath Temporal. This duplicates durable
  execution authority and obscures whether the application or Temporal owns recovery.

## Approval

- Mode: Collaborative
- Decision owner: Requester
- Approved on: 2026-08-10
- Accepted decisions: `channel-260810/ADR-D1`, `channel-260810/ADR-D2`
- Approved scope: one common producer-local Job Runtime for current execution and one
  deployment-wide configured backend when a future Temporal implementation is adopted
