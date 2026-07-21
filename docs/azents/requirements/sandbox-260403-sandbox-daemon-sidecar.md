---
title: "sandbox-daemon Sidecar Separation + kube API Exec Integration Historical Requirements Reconstruction"
created: 2026-04-03
implemented: 2026-04-03
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sandbox-260403
historical_reconstruction: true
migration_source: "docs/azents/design/sandbox-daemon-sidecar.md"
---

# sandbox-daemon Sidecar Separation + kube API Exec Integration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sandbox-260403`
- Source: `docs/azents/design/sandbox-260403-sandbox-daemon-sidecar.md`
- Historical source date basis: `2026-04-03`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Separate sandbox-daemon from agent-runtime container and operate it as separate Kubernetes sidecar container, changing structure so commands are executed in user container through kube API exec.

**Problems solved:**
- Updating sandbox-daemon requires rebuilding entire agent-runtime image.
- All processes run in single container → resource isolation impossible.
- supervisord manages process lifecycle → K8s native healthcheck/restart not used.

**Things not changed:**
- `SandboxDaemonClient` HTTP interface (keep nointern server → daemon communication path).
- File API path routing (direct access to shared volume `/mnt/agent-data`).
- Per-user isolation model (decided in separate discussion).

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
