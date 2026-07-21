---
title: "Idempotent Sandbox Lifecycle State Historical Requirements Reconstruction"
created: 2026-05-24
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: idempotent-260524
historical_reconstruction: true
migration_source: "docs/azents/design/idempotent-sandbox-lifecycle.md"
---

# Idempotent Sandbox Lifecycle State Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `idempotent-260524`
- Source: `docs/azents/design/idempotent-260524-idempotent-sandbox-lifecycle.md`
- Historical source date basis: `2026-05-24`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Sandbox lifecycle control currently mixes desired-state changes, provider lease
allocation, process-local attach, and Kubernetes Pod reconciliation behind
`ensure_ready()`. That makes a harmless user/API action such as "start sandbox"
able to produce a fresh provider allocation. In the K8s provider this can delete
and recreate the sandbox Pod when the existing Pod's provider generation/token
does not match the new allocation.

That is unsafe because the K8s provider mounts `/home/sandbox` as Pod-local
`emptyDir`. If a Pod is deleted before a checkpoint is committed, user-visible
workspace data is lost.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Sandbox state changes are idempotent desired-state transitions.
- Worker/API code does not decide whether to create, delete, or recreate K8s
  Pods.
- Kubernetes provider remains the resource reconciler for desired runtime state.
- ACTIVE runtime attach is non-destructive and never allocates a new backend.
- Persist/restore transitions are data-safe and retryable.
- Destructive recovery is explicit and gated by a durability precondition:
  checkpoint exists, provider-native `preserve_home`, or operator/user-approved
  discard.

## Non-goals

- Adding a new `desired_runtime_state` database column in this PR.
- Changing provider-control protocol messages in this PR.
- Introducing provider-native K8s persistent volumes in this PR.

Those are follow-up hardening items. The immediate safety fix is to stop
ACTIVE start/read paths from invoking allocation/recreate.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
