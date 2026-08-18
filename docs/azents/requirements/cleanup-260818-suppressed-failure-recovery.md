---
title: "Suppressed Failure Observation and Recovery Requirements"
created: 2026-08-18
updated: 2026-08-18
implemented: 2026-08-18
tags: [backend, runtime, cleanup, observability, avatar]
document_role: primary
document_type: requirements
snapshot_id: cleanup-260818
---

# Suppressed Failure Observation and Recovery Requirements

- Snapshot: `cleanup-260818`
- Document reference: `cleanup-260818/REQ`

## Problem

Several detached-task and cleanup boundaries intentionally preserve an already
determined timeout, cancellation, transfer, avatar replacement, or avatar removal
result. Some of those boundaries currently discard later exceptions without a
stack trace or retained cleanup evidence.

Operators therefore cannot reliably distinguish successful cleanup from leaked
resources. Avatar replacement and removal can also lose the only pointer to an
old public avatar after the Agent database mutation succeeds, leaving no durable
retry responsibility.

## Primary Actor

An operator diagnosing and recovering background cleanup failures without
changing the result already returned to an Azents user.

## Primary Scenario

A primary operation reaches its authoritative timeout, cancellation, transfer,
avatar replacement, or avatar removal result, and a detached task or cleanup
operation then fails. The primary result remains unchanged. The failure is
recorded once with bounded, content-safe context, and cleanup that owns durable
application data remains eligible for a later retry until it succeeds.

## Supporting Scenarios

- A model-stream support task fails after caller cancellation or timeout.
- A local job handler raises while settling inside cancellation grace.
- Runtime-to-Server transfer cleanup cannot confirm abandonment or cancellation
  after bounded recovery attempts, and its last handled failure has no remaining
  observer.
- Runtime Transfer multipart or completed-object cleanup fails and its existing
  retry state retains an actionable bounded failure classification.
- Avatar replacement or removal succeeds while deletion of the previous public
  avatar fails temporarily.
- Two avatar mutations overlap and each superseded avatar remains identified for
  cleanup without deleting the final current avatar.

## Goals

- Make suppressed detached-task and cleanup failures observable.
- Assign exactly one stack-trace logging owner to each handled exception.
- Retain bounded Runtime Transfer cleanup diagnostics with existing retry state.
- Make old-avatar blob deletion durably retryable after replacement or removal.
- Preserve existing public API and primary operation outcomes.

## Non-Goals

- Turning handled cleanup failures into failures of an already committed primary
  operation.
- Adding exception stack traces, raw provider messages, storage object keys, raw
  provider upload identifiers, credentials, endpoints, file contents, or hashes
  to Runtime Transfer cleanup diagnostic evidence.
- Making volatile Runtime Transfer state a relational product entity.
- Exposing internal cleanup diagnostics through a new public API.
- Recovering avatar blobs published before a replacement is adopted by the
  Agent database mutation, including partial thumbnail publication. That
  pre-adoption compensation lifecycle is separate future work.
- Fixing unrelated detached-resource finalization behavior that does not affect
  the identified suppressed exceptions.

## Requirements

### REQ-1. Exact-owner detached failure observation

When no upstream observer remains for a detached or cleanup task exception, the
owning boundary must record the exception once without changing the primary
timeout or cancellation outcome.

**Acceptance criteria**

- Late model-stream operation and owned support-task failures include a stack
  trace and bounded stream/task context.
- A job handler that raises while settling inside cancellation grace includes a
  stack trace and bounded job identity.
- A Runtime-to-Server transfer cleanup failure is recorded once only after
  bounded terminal-status recovery and cancellation confirmation are exhausted;
  authoritative terminal recovery remains silent.
- Expected cancellation does not produce an error record.
- The same exception is not independently stack-trace logged by multiple
  boundaries.
- The original timeout or cancellation result remains unchanged.

### REQ-2. Actionable Runtime Transfer cleanup evidence

Runtime Transfer cleanup failure evidence must remain attached to the existing
retry responsibility and must be safe for volatile operational state.

**Acceptance criteria**

- Multipart-abort and completed-object-delete failures retain a bounded stable
  cleanup classification and observation metadata with retryable cleanup state.
- Successful cleanup clears obsolete failure evidence.
- Memory and Redis transfer-state implementations expose equivalent behavior.
- Runtime Transfer continues to retry through its existing bounded repair paths.
- Transfer bytes and sensitive or provider-specific storage details are not added
  to state or logs.
- No PostgreSQL transfer entity or public transfer API is introduced.

### REQ-3. Durable old-avatar cleanup after replacement or removal

Once avatar replacement or removal commits, every superseded avatar must retain
durable cleanup responsibility until all of its public blobs are deleted.

**Acceptance criteria**

- The Agent avatar mutation and creation of cleanup responsibility for the prior
  avatar commit atomically.
- The avatar mutation succeeds even when immediate blob deletion is unavailable.
- A bounded periodic cleanup pass retries pending avatar deletions.
- Cleanup failure retains bounded diagnostic and attempt evidence and emits one
  stack-trace log for the failed attempt.
- Cleanup success removes or terminally completes the pending responsibility.
- Concurrent replacement and removal cannot cause the final current avatar to be
  selected as obsolete cleanup work.
- Agent deletion does not erase cleanup responsibility for an already
  superseded avatar.

### REQ-4. Compatibility and operational boundaries

The correction must preserve existing external contracts and established cleanup
authority.

**Acceptance criteria**

- Agent avatar API routes and response models remain unchanged.
- Runtime Transfer does not add a legacy fallback or mixed-version compatibility
  path.
- Redis remains optional and may be restored empty without blocking new
  transfers.
- Existing scheduler and cleanup work remains bounded.
- Structured diagnostics use stable identifiers and classifications rather than
  unbounded exception content.

## Fixed Constraints

- Primary timeout, cancellation, transfer, avatar replacement, and avatar removal
  outcomes remain authoritative.
- Only the boundary that handles and suppresses an exception logs its stack trace.
- Runtime Transfer state remains metadata-only, bounded, internal, and volatile.
- Redis is optional and cannot be required for durable avatar cleanup.
- Durable avatar cleanup authority must survive process restarts and Agent
  deletion.
- The work is delivered in one pull request and is not merged without explicit
  requester approval.

## Open Assumptions

- Public avatar deletion is idempotent when the object is already absent.
- The existing file lifecycle scheduler cadence is sufficient for avatar cleanup
  retry latency.
- The currently selected Redis transfer-record schema can use a coordinated
  application cutover without a mixed-version compatibility reader.

## Confirmation

Confirmed by the requester on 2026-08-18 through the explicit request to resolve
GitHub issue #1322 in one pull request while preserving primary outcomes,
retaining transfer cleanup diagnostics, and making avatar deletion durably
retryable after replacement or removal.
