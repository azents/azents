---
title: "Adopt AgentRuntime-Based Sandbox Control Channel Historical Requirements Reconstruction"
created: 2026-05-06
implemented: 2026-05-06
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sandbox-260506
historical_reconstruction: true
migration_source: "docs/azents/adr/0008-agent-runtime-sandbox-control-channel.md"
---

# Adopt AgentRuntime-Based Sandbox Control Channel Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sandbox-260506`
- Source: `docs/azents/adr/sandbox-260506-sandbox-control-channel.md`
- Historical source date basis: `2026-05-06`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The current NoIntern sandbox control path has the nointern worker/API discover a Kubernetes Pod IP or Docker container network address, then call the `sandbox-daemon` sidecar HTTP API inbound. This was useful as an intermediate step for isolating helper processes from custom/root sandbox containers, but it does not fit the default product sandbox model.

The current model has these major limitations:

1. Sandbox discovery and control are tightly coupled to Kubernetes Pod IPs, sidecar HTTP ports, and daemon readiness.
2. The name and public API of `SessionSandboxManager` imply session-bound ownership. In reality, the sandbox lifecycle owner is `AgentRuntime`, not `AgentSession`.
3. File read/write is based on whole-body request/response, making large file streaming, backpressure, and resume difficult to express.
4. External sandbox vendors, local-machine sandboxes, and controlled sandbox images should have the sandbox client register outbound instead of having nointern connect inbound.
5. Delivering commands through Kubernetes exec inside the same Pod unnecessarily binds the command/file control plane to the Kubernetes API.

Issue #3426 and Discussion #3445 decided on the following direction.

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
