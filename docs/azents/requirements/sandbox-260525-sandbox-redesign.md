---
title: "Sandbox System Redesign Historical Requirements Reconstruction"
created: 2026-05-25
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sandbox-260525
historical_reconstruction: true
migration_source: "docs/azents/adr/0038-sandbox-system-redesign.md"
---

# Sandbox System Redesign Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sandbox-260525`
- Source: `docs/azents/adr/sandbox-260525-sandbox-redesign.md`
- Historical source date basis: `2026-05-25`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Legacy Sandbox system grew from session-bound command execution into mixed runtime platform. Terms and responsibilities for Runtime, Sandbox, Session Workspace, Provider, sandbox-control, sandbox daemon, checkpoint, and file workspace became entangled.

Recurring issues:

- UI sometimes displayed Sandbox as stopped while backend resource was running, or exposed file/bash operations while Runner was not ready.
- API, Worker, and UI inferred lifecycle state and in-runtime operation availability from same source.
- Non-durable process-local handle/cache/active-session lookup became implicit source of truth in distributed system.
- Query APIs created side effects such as starting sandbox or observing provider.
- `/home/sandbox` path and S3 checkpoint/restore implementation leaked into domain contracts.
- Provider, Runner, and Control were coupled inside server process, making rollout/reconnect/failover fragile.

We need a clean domain model: Agent-scoped Runtime, external Provider, in-runtime Runner, stateless Control, explicit coordination store, and server-owned state summary.

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
