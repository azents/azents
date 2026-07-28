---
title: "Runtime Transfer Lifespan Recovery Requirements"
created: 2026-07-28
updated: 2026-07-28
implemented: 2026-07-28
tags: [runtime, transfer, storage, redis, cleanup]
document_role: primary
document_type: requirements
snapshot_id: transfer-260728
---

# Runtime Transfer Lifespan Recovery Requirements

- Snapshot: `transfer-260728`
- Document reference: `transfer-260728/REQ`

## Problem

Runtime Transfer already limits logical access to one hour and attempts immediate
object deletion or multipart abort when an attempt settles. Two deployment and
recovery gaps remain:

- Runtime Control startup can be blocked by chart values that only attest to an
  external storage lifecycle policy and have no runtime enforcement role.
- When the selected volatile transfer-state backend is reset, objects and
  incomplete multipart uploads can remain without a state record that identifies
  them for cleanup.

These gaps can prevent `present_file` from working after a chart rollout and can
make orphan cleanup depend on Redis retention or a backend lifecycle schedule.

## Primary Actor

A user asking an Agent to publish a Runtime file with `present_file`.

## Primary Scenario

The deployment uses external S3-compatible workspace storage and either the
in-memory or Redis transfer-state implementation. Runtime Control starts from
functional object-storage configuration without requiring a declaration-only
lifecycle acknowledgement. The Agent publishes a Runtime file successfully.
If volatile transfer state is later lost and restarted empty, Runtime Transfer
resumes accepting new work and independently discovers and cleans expired
transfer-prefix objects and incomplete multipart uploads without treating those
artifacts as successful transfer state.

## Supporting Scenarios

- A transfer settles successfully, fails, is cancelled, times out, is superseded,
  or is abandoned and immediately attempts exact object or multipart cleanup.
- Exact cleanup fails temporarily and state-backed repair retries while its
  bounded record remains available.
- Runtime Control restarts with an empty in-memory store or an empty restored
  Redis store and fails closed for prior attempts while continuing new transfers.
- Multiple Runtime Control replicas observe the same expired storage artifact and
  perform idempotent cleanup without requiring a Redis lock.
- Storage lifecycle processing runs later than the one-hour logical boundary and
  remains only a final orphan-defense mechanism.

## Goals

- Keep the one-hour transfer validity limit authoritative and non-extendable.
- Restore `present_file` startup without invented lifecycle acknowledgement
  values.
- Make orphan cleanup survive complete volatile transfer-state loss.
- Preserve Redis as an optional, ephemeral shared-state implementation.
- Keep object-store lifecycle policy separate from Runtime Transfer authorization.

## Non-Goals

- Retaining transfer bytes for debugging or audit history.
- Turning transfer state into a relational product entity.
- Giving Runner object-store credentials, keys, or presigned URLs.
- Guaranteeing that an S3-compatible backend physically removes an object at the
  exact instant its one-hour logical lifetime ends.
- Adding a standalone storage lifecycle Job owned by the Azents application chart.
- Supporting old declaration-only lifecycle acknowledgement values after the
  coordinated deployment configuration is updated.

## Requirements

### REQ-1. Functional Runtime Control startup

Runtime Control deployment must depend only on configuration that the runtime
uses to provide and secure Runtime Transfer.

**Acceptance criteria**

- External S3-compatible storage can render and start Runtime Control without a
  lifecycle acknowledgement object.
- Runtime Control receives its transfer bucket, endpoint, credentials, object
  prefix, and Runner transfer endpoint.
- Removed lifecycle acknowledgement values are rejected rather than silently
  becoming lifespan authority again.
- A deployment overlay is updated in the same coordinated rollout before it uses
  the schema that removes those values.

### REQ-2. One-hour logical authority and immediate cleanup

Every transfer attempt must remain logically usable for no longer than one hour
from admission and must attempt physical cleanup as soon as content is no longer
needed.

**Acceptance criteria**

- State transitions, retries, leases, and consumer activity do not extend an
  attempt beyond its original one-hour logical expiration or an earlier source
  expiration.
- Every access rejects an expired attempt even when its object still exists.
- Success, failure, cancellation, timeout, integrity rejection, supersession, and
  consumer abandonment immediately attempt exact object deletion or multipart
  abort.
- Physical cleanup failure remains observable and retryable but does not reverse
  an already committed user-visible result.

### REQ-3. Volatile-state-loss recovery

Runtime Transfer must recover after its selected volatile state implementation
returns empty and must not require historical Redis data to clean storage
orphans.

**Acceptance criteria**

- Prior attempts fail closed when their transfer-state records are unavailable.
- New transfers can be admitted after the in-memory store or Redis is restarted
  empty.
- Runtime Control scans the transfer-owned storage prefix in bounded pages and
  identifies completed objects and incomplete multipart uploads old enough to
  be outside the one-hour transfer lifetime.
- Eligible artifacts are deleted or aborted idempotently without reconstructing
  successful transfer state from storage.
- The recovery behavior is identical for memory and Redis state backends.

### REQ-4. Storage lifecycle remains final defense

Object-storage lifecycle policy must remain an infrastructure-owned, coarse final
defense rather than an application authorization or deployment-attestation input.

**Acceptance criteria**

- Runtime Control does not read lifecycle acknowledgement durations, owners, or
  timestamps.
- The Helm chart does not block Runtime Control startup on declaration-only
  lifecycle evidence.
- Backend lifecycle timing is not described as a one-hour physical deletion
  guarantee.
- Deployments may configure the shortest supported transfer-prefix object
  expiration and incomplete-multipart abort policy outside Runtime Transfer
  runtime configuration.

## Fixed Constraints

- The one-hour Runtime Transfer validity limit is fixed.
- Immediate best-effort object deletion and multipart abort remain the normal
  settlement path.
- Redis is optional and ephemeral. It may provide shared coordination but is not
  durable transfer authority.
- An empty restored Redis instance must allow the service to resume.
- Object existence is byte evidence only and never recreates transfer success,
  authorization, consumer claims, or terminal state.
- Runner remains untrusted and never receives storage authority.
- Runtime Control performs bounded streaming and cleanup without whole-file
  buffering.
- Existing implemented Runtime File Transfer Requirements, ADR, and Design
  remain immutable historical records.

## Open Assumptions

- S3-compatible storage exposes paginated object listing with modification time
  and paginated multipart-upload listing with initiation time.
- Exact object deletion and multipart abort are idempotent or return a
  not-found result that Runtime Control can treat as already cleaned.
- Storage-side lifecycle support and execution timing vary by backend.

## Confirmation

Confirmed by the requester on 2026-07-28. The requester fixed the one-hour
lifespan, immediate cleanup, Redis-optional and empty-restore recovery behavior,
and rejected invented lifecycle durations or standalone lifecycle Jobs.
