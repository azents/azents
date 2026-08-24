---
title: "Runtime System Metrics Overview Requirements"
created: 2026-08-24
updated: 2026-08-24
implemented: 2026-08-24
tags: [runtime, metrics, frontend, observability]
document_role: primary
document_type: requirements
snapshot_id: runtime-260824
---

# Runtime System Metrics Overview Requirements

- Snapshot: `runtime-260824`
- Document reference: `runtime-260824/REQ`

## Problem

Users can observe whether an Agent Runtime is running and available, but they cannot see whether the execution environment visible to its Runner is under CPU, memory, or disk pressure. External observability systems are too detailed for the ordinary product workflow, while the absence of a lightweight overview makes it difficult to judge whether a Runtime is healthy enough for current Agent work.

## Primary Actor

A user authorized to access an Agent.

## Primary Scenario

While working with an Agent in chat, the user opens the Runtime/Workspace panel and immediately sees the current CPU, memory, and disk usage of the current Runner execution environment together with a compact recent trend, measurement scope, freshness, and availability state. The user can determine whether the Runtime has sustained resource pressure without leaving Azents or using an infrastructure observability product.

## Supporting Scenarios

- A user opens the overview after the panel has been closed and can see samples collected before the panel was opened.
- A Provider-managed Runtime reports the host, virtual machine, or container environment visible to its Runner without requiring Provider-side infrastructure metrics.
- A future user-provisioned Runtime can report the host, virtual machine, or container environment in which its Runner executes without requiring a Provider.
- A Runtime that cannot currently report one or more metrics presents the unavailable or stale state explicitly instead of displaying a fabricated zero or unrelated host value.

## Goals

- Provide a lightweight CPU, memory, and disk overview inside the ordinary Agent workflow.
- Show both the latest measurement and enough recent context to distinguish a brief change from sustained pressure.
- Preserve the actual execution scope visible to the Runner across host, virtual-machine, and container topologies.
- Make metric freshness, partial availability, and scope understandable without exposing infrastructure internals.
- Keep the overview safe for every user who is already authorized to access the Agent.

## Non-Goals

- Long-term metric retention, historical search, arbitrary time-range selection, export, or analytics.
- Alerting, anomaly detection, SLOs, capacity planning, billing, or automated Runtime scaling.
- Per-process, per-container, per-sidecar, per-volume, or per-mount breakdowns.
- Provider-side infrastructure collection or aggregation of other containers and sidecars outside the Runner's observable environment.
- Hostnames, filesystem paths, process lists, infrastructure resource names, or other device-identifying diagnostics.
- Agent Workspace content-size accounting as a substitute for Runtime system disk usage.
- Implementing user-provisioned Runtime enrollment or pairing in this snapshot.

## Requirements

### REQ-1. Show current Runtime system resource usage

Azents must show the latest available CPU, memory, and disk usage for the current Runner execution environment of an Agent Runtime.

**Acceptance criteria**

- The overview presents CPU usage, memory usage, and disk usage as separate user-readable values.
- Usage is paired with the relevant total or limit when that value is available.
- The overview does not fabricate a percentage when the applicable total or limit is unavailable.
- Every latest measurement includes its measurement time and freshness state.
- A metric that is unsupported or temporarily unavailable is presented explicitly and independently from the other metrics.

### REQ-2. Show a bounded recent trend

Azents must show a compact recent trend that is available immediately when the user opens the Runtime/Workspace panel.

**Acceptance criteria**

- The trend covers the most recent one hour.
- The trend contains at most one sample per minute and at most 60 samples per metric.
- The latest value and trend use the same metric definitions and execution-environment scope.
- Missing intervals remain visible as gaps or unavailable data and are not silently interpolated as observed values.
- The recent trend is best-effort overview data: a control-plane or short-term-store restart may clear earlier samples without affecting Runtime correctness.
- Samples older than one hour are not returned through the product overview.

### REQ-3. Preserve the Runner execution-environment scope

Metrics must describe the physical host, virtual machine, or container environment that the current Runner can observe without claiming a broader Provider or infrastructure scope.

**Acceptance criteria**

- Each metric snapshot identifies a bounded scope such as host, virtual machine, or container.
- A Provider-managed Runtime reports the environment visible to its Runner and does not aggregate other Provider-owned containers or sidecars.
- A directly run Runner reports the host, virtual machine, or container environment in which it executes.
- Azents does not substitute node, Provider-host, or control-plane usage for a container-scoped Runner.
- Metrics from a previous Runtime generation or replaced physical incarnation never appear as current measurements for the new incarnation.

### REQ-4. Keep access aligned with Agent access

Every user authorized to access an Agent must be able to view that Agent Runtime's system metrics overview.

**Acceptance criteria**

- The metrics API and UI use the existing Agent access boundary and do not create a separate metrics-owner role.
- Unauthorized users cannot read either the latest sample or recent trend.
- The overview excludes hostnames, filesystem paths, process identities, raw infrastructure identifiers, and other device-identifying details.
- User-provisioned and Provider-managed Runtimes follow the same Agent access rule.

### REQ-5. Represent freshness and lifecycle accurately

The overview must distinguish a fresh current sample from stale, unavailable, stopped, disconnected, or unsupported metric state.

**Acceptance criteria**

- A user can see when the latest sample was measured.
- A Runtime that stops producing samples does not continue to present an old sample as current.
- A stopped or disconnected Runtime may retain its bounded recent trend, but the UI identifies that no fresh current measurement is available.
- Starting, replacing, resetting, or rearming a Runtime cannot make samples from an earlier physical incarnation appear current.
- Metric collection or storage failure does not change Runtime lifecycle state or block ordinary Runtime operations.

### REQ-6. Present the overview in the Runtime workflow

The primary metrics overview must be available from the chat Runtime/Workspace panel, with an equivalent secondary entry point from Agent Runtime settings.

**Acceptance criteria**

- The Runtime/Workspace panel shows compact current CPU, memory, and disk values and a recent trend without requiring navigation to an Admin surface.
- The overview remains understandable on desktop and mobile layouts.
- Agent Runtime settings can expose the same metric state without defining a second metric contract.
- Unsupported, empty, stale, and partially available states have explicit user-visible presentations.

## Fixed Constraints

- Runtime, Provider, and Runner remain separate authority and connection planes.
- A Provider is optional in the general Runtime contract even though the current product implementation provisions managed Runtimes through Providers.
- Metric reports are untrusted Runtime-originated observations and cannot grant lifecycle, Provider, Agent, Workspace, or control-plane authority.
- The overview is informational and cannot become an authority for billing, lifecycle reconciliation, scheduling, or destructive operations.
- Recent trend loss must not affect Runtime correctness, current lifecycle state, Agent Workspace durability, or ordinary Runner operations.

## Open Assumptions

- CPU is presented as average usage over each one-minute sample interval; memory and disk are point-in-time usage measurements for that interval.
- The overview presents one aggregate disk value for the reported execution environment; per-volume and per-mount detail remains outside this snapshot.
- A current measurement becomes stale after a bounded number of missed one-minute reports; the exact threshold will be resolved in design without changing the one-hour history contract.

## Confirmation

Confirmed by the requester on 2026-08-24 before ADR and design decisions began.
Amended and reconfirmed by the requester on 2026-08-24 to use the minimal
Runner-observable execution scope without Provider-side aggregation.
