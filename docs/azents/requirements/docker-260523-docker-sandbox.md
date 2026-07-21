---
title: "Introduce system Docker Sandbox Provider Historical Requirements Reconstruction"
created: 2026-05-23
implemented: 2026-05-23
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: docker-260523
historical_reconstruction: true
migration_source: "docs/azents/adr/0037-system-docker-sandbox-provider.md"
---

# Introduce system Docker Sandbox Provider Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `docker-260523`
- Source: `docs/azents/adr/docker-260523-docker-sandbox.md`
- Historical source date basis: `2026-05-23`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

After provider-control rollout, we needed a provider implementation that can reproduce and isolate production K8s provider issues locally. The current local dev path has `DockerSessionSandboxClient`, but that backend has the worker process directly control Docker. Therefore it cannot verify provider-control stream, provider heartbeat, lease, or provider-owned lifecycle command routing.

The customer local Docker provider discussed in separate issues #3906/#3916 is a workspace-scoped provider daemon running on a customer's machine. That product feature includes login UX, provider credential, public TLS, credential revoke, workspace provider UI, and local-machine trust boundary hardening. The purpose here is not to implement that feature. It is to manage Docker runtime as a system-level provider inside NoIntern devserver/testenv so K8s provider issues can be separated from provider-control core issues.

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
