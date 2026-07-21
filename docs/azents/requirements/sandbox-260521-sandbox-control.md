---
title: "Introduce SandboxProviderControl Historical Requirements Reconstruction"
created: 2026-05-21
implemented: 2026-05-08
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sandbox-260521
historical_reconstruction: true
migration_source: "docs/azents/adr/0035-sandbox-provider-control.md"
---

# Introduce SandboxProviderControl Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sandbox-260521`
- Source: `docs/azents/adr/sandbox-260521-sandbox-control.md`
- Historical source date basis: `2026-05-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[sandbox-260506/ADR](../adr/sandbox-260506-sandbox-control-channel.md) adopted a structure where an in-sandbox client opens an outbound `SandboxControlRuntime.Connect` gRPC stream to NoIntern, and the worker requests command/file/checkpoint operations through `SandboxControlWorker`. This decision separated command/file/checkpoint transport from Kubernetes Pod IP, Docker network discovery, and inbound sidecar daemon calls.

However, the sandbox **lifecycle provider** still has NoIntern worker/control plane directly creating Kubernetes Pods or local Docker containers. This structure does not sufficiently express the following requirements:

1. Providers outside the NoIntern-managed Kubernetes cluster must be able to provide sandbox capacity.
2. To support customer/local Docker providers long term, the provider must connect outbound to NoIntern without exposing inbound ports.
3. K8s-based provider controller should be separated as an optional component in the NoIntern Helm chart so operational topology is explicit.
4. Provider identity, active liveness, runtime allocation lease, and sandbox-control runtime registration auth must have separate state authorities.
5. The durable contract preserved on hibernate/resume must clearly distinguish `/home/sandbox/**` from rootfs/S3 snapshot/container snapshot.

In issue #3914 Phase 2 design discussion, we decided to first settle the direction of SandboxProviderControl and leave detailed local Docker provider UX/daemon implementation downstream.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
