---
title: "Agent Runtime Persistence"
created: 2026-05-25
tags: [backend, engine, infra]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, workspace, conversation]
code_paths:
  - python/apps/azents/src/azents/rdb/models/agent_runtime.py
  - python/apps/azents/src/azents/rdb/models/runtime_profile.py
  - python/apps/azents/src/azents/repos/agent_runtime/**
  - python/apps/azents/src/azents/repos/runtime_profile/**
  - python/apps/azents/src/azents/services/agent_runtime/**
  - python/apps/azents/src/azents/services/runtime_profile_reconciliation/**
  - python/apps/azents/src/azents/services/runtime_profile_resolution/**
  - python/apps/azents/src/azents/services/runtime_recreation/**
  - python/apps/azents/src/azents/services/chat/workspace.py
  - python/apps/azents/src/azents/services/session_workspace_project/**
  - python/apps/azents/src/azents/runtime/**
  - python/apps/azents-runtime-provider-docker/**
  - python/apps/azents-runtime-provider-kubernetes/**
  - python/apps/azents-runtime-runner/**
  - infra/charts/azents/**
last_verified_at: 2026-08-04
spec_version: 15
---

# Agent Runtime Persistence

## Overview

Agent Workspace durability is owned by the Runtime Provider backend, not by the Azents server
process and not by S3 checkpoint/restore as an event path. The current-generation Runner reports
the effective Agent Workspace absolute path as Runtime metadata. Server file APIs, Projects,
worktrees, and prompts consume that reported path without a fixed server-side fallback.

## Runtime Profile binding and configuration revisions

An Agent stores one exact Workspace Runtime Profile selection or no selection. When the logical
Runtime row is ensured, the Runtime Profile resolver reads that exact Profile and persists the
logical/durable Provider routing IDs, infrastructure Profile ID, Workspace Runtime Profile ID, and
an immutable desired configuration revision. It does not consult a Provider preference, Platform
default, environment default, or fallback.

The desired revision records the exact Provider capability revision, infrastructure and Workspace
Profile IDs/versions/digests, Agent selection version, resolved full configuration, source trace,
target desired generation, and canonical digest. A blocked resolution is also durable and keeps its
bounded reason and missing-capability evidence without discarding the last applied revision.

The applied revision pointer is separate physical evidence. It advances only after the exact
Provider acknowledges the current revision and the ordinary Runner state report returns the same
generation and digest. Desired changes therefore become visible immediately while the running
incarnation may remain applied to an older revision or wait for explicit recreation.

Capability/Profile changes never reassign the Agent to another Provider or Profile. Provider or
Profile loss preserves IDs, revisions, and existing storage while blocking new create/start/restart/
reset/recreate work. Historical hierarchy conversion occurs only inside the one-way Alembic
migration; runtime services do not read legacy policy tables, snapshots, overrides, or status
fallbacks.

## Event Persistence

| Provider | Event persistence | Scope |
|---|---|---|
| Kubernetes Provider v2 | EBS-backed PVC per Runtime | Production Kubernetes path |
| Docker Provider v1 | Per-Runtime host directory bind mount on a stable single Docker host | Local/dev single-host path |

S3/RustFS checkpoint objects are not the event persistence contract for Agent Runtime v1.
Legacy checkpoint rows may remain for older data/model compatibility, but new Runtime lifecycle
correctness must not depend on checkpoint commit/restore.

## Workspace Path Contract

Runner resolves an explicit startup path before `HOME`, normalizes it, requires an absolute
non-empty value, and reports it during registration and state updates. Control stores valid
current-generation evidence on the Runtime row and exposes it through server-computed
workspace/bootstrap responses.

Providers choose their deployment mount paths and configure Runner `HOME` and working directory to
the mount. They do not report, approve, or clear Agent Workspace metadata. Missing or invalid Runner
evidence makes workspace operations unavailable, and a new desired generation clears the previous
path until its Runner reports current evidence.

## Destructive Operation Boundary

Only explicit `reset` and terminal delete may delete Agent Workspace data.

- `start` may create compute and attach durable storage; it must not wipe existing workspace bytes.
- `stop` may stop compute; it must preserve durable storage.
- `restart` may recreate compute; it must preserve durable storage.
- `recover` and reconciliation may repair stale backend/control state; they must preserve durable
  storage.
- ordinary Runtime Profile recreation may replace compute; it must preserve durable storage.
- `observe` is read-only.

For desired-running Runtimes, periodic reconciliation uses idempotent `start` to compare the
Provider-managed workload against the current Runner image and configuration. Equivalent workloads
are reused. Drifted Docker containers or Kubernetes Pods are replaced while the host workspace
directory or PVC remains intact.

Any ambiguous backend outcome is treated as unavailable or retryable until Provider evidence proves
the desired state. Ambiguity is not permission to delete the workspace.

## Kubernetes Provider v2

Kubernetes Provider v2 is an external process that talks to the Kubernetes API and Runtime Control
gRPC. It uses Lease leader election so only the active leader issues lifecycle commands for a
provider id.

Current Runtime Control admits only protocol `agent-runtime-provider-kubernetes-v2`; v1 is rejected
before capability contract proposal, durable connection registration, or command authority. There
is no mixed-version operation or legacy report fallback.

A healthy non-leader process reports Kubernetes readiness while it can inspect the leader Lease, so
a single-replica rolling Deployment can replace the old leader without waiting for the standby to
become active first. On leadership acquisition, the process clears readiness until Runtime Control
authentication and registration succeed. Standby processes do not open the authoritative Control
stream or mutate Runtime resources.

The active Provider keeps the Kubernetes Pod watch as a long-lived request without a client total or
socket-read deadline. Normal server-side watch completion is reopened independently and does not
rotate the authoritative Runtime Control connection.

For each Runtime, the provider creates or reuses an EBS-backed PVC and mounts it at its configured
Runner home path in the Pod. PVC identity is tied to Runtime identity/generation labels
and fenced by Control generation. Stale observations cannot overwrite newer desired generations.

Reset is the only non-terminal command that may delete and recreate the PVC contents. Terminal
delete removes the PVC without recreating it. Stop/restart/recover and ordinary recreation must not
delete the PVC.

The Runtime Profile topology is typed Provider infrastructure, not arbitrary Pod input. A Profile
without DinD contains only the unprivileged Runner. A DinD-enabled Profile adds one
privileged DIND sidecar and mounts its Runtime-private Unix socket read-only into the Runner. There
is no Docker API Gateway or partial operation allowlist. The complete Docker capability supports
CLI, Compose, SDK, Testcontainers, Ryuk, and port-binding workflows supported by the daemon.
The Runner and DIND sidecar mount the Agent Workspace PVC at the same configured absolute
path and mount one Pod-local shared temporary volume at `/tmp`, bounded by the Profile's Runtime
ephemeral-storage allocation. Docker bind mounts sourced from the Agent Workspace or `/tmp`,
including Compose paths relative to the Agent Workspace, therefore resolve to the same files from
the Docker daemon's mount namespace. Other Runner root-filesystem paths are not shared bind-mount
sources.

The Runner and nested workloads do not receive the Provider ServiceAccount, Provider credentials,
host Docker socket, or another Runtime's DIND socket. Agent Workspace PVC storage remains distinct
from temporary Docker data, which uses a bounded engine-only `emptyDir`. The Profile may set the
DIND sidecar's Kubernetes CPU/memory requests and limits and fixed ephemeral-storage allocation.
PID, nested-container count, and per-Profile network fields are not advertised because direct
privileged Docker authority bypasses such in-daemon policy claims.

The Runtime-specific Kubernetes NetworkPolicy is the intersection of the Provider hard boundary,
the selected Pod Profile preset, and any Workspace narrowing. Required DNS and Runtime Control
traffic remains protected. Resolution uses the exact Provider's current valid capability revision,
never raw unvalidated metadata or an older historical revision. The Pod Profile separately controls
Agent Workspace PVC capacity. Expansions may apply to the existing PVC; shrink remains deferred
until an explicit reset or terminal deletion recreates storage.

Pod lifecycle observation is independent of NetworkPolicy verification history. Explicit command
reports may carry exactly one structured `network_policy` result, while watch, failover, and
lifecycle-only reports may omit it. Runtime Control persists current drift evidence with Provider
generation, desired generation, configuration revision, observation time, and bounded reason. It
atomically claims matching `drifted` evidence for retry-throttled non-destructive
`UPDATE_CONFIGURATION`; stale evidence cannot dispatch, and matching `in_sync` evidence replaces the
drift candidate. Unsupported evidence kinds reject the complete report before persistence.

## Docker Provider v1

Docker Provider v1 assumes one stable Docker host. For each Runtime it creates a host directory and
bind-mounts it into the Runner container at its configured Runner home path. The host directory is
the event persistence source.

Stop/restart/recover and ordinary recreation may remove/recreate containers, but must keep the host
directory. Reset may delete or replace the host directory according to the reset command. Terminal
delete removes both the container and host directory.

## Agent Workspace Projects

Session Workspace Project registry rows are AgentSession-scoped DB state. They are not derived from
filesystem snapshots. Runtime persistence preserves the bytes; the session registry preserves which
child paths are registered or awaiting registration approval for the selected conversation.

Project paths are normalized as children of the current Runner-reported Agent Workspace root. The root
itself is not a Project. Runtime persistence does not own Project membership. azents-web exposes
Project management inside the concrete session Workspace surface. The Workspace browser opens in
Project mode by default, keeps `All files` as an explicit Agent Workspace root inspection mode, and
uses backend Project browser manifest capabilities so Project root removal is registry-scoped rather
than filesystem-destructive.

## Validation

Required checks:

- Docker provider tests show stop/restart preserves the host directory and reset is destructive.
- Kubernetes provider tests render PVC-backed Runtime resources and leader-election settings.
- Workspace service tests reject missing current Runner workspace paths with explicit errors.
- Runner state sink tests persist normalized Runner path authority and reject missing or invalid paths.
- Provider tests verify configured mount, Runner `HOME`, and working-directory alignment without Provider workspace reports.
- Deterministic azents E2E covers Agent Workspace bootstrap and reset action availability.
- Runtime Profile E2E uses Admin/Public API setup and a real Docker Provider to verify unconfigured,
  default, and explicit selection; exact desired/applied evidence; explicit recreation; Provider
  loss without substitution; retained selection; and recovery.
- Migration tests prove exact legacy effective-selection conversion and final absence of obsolete
  policy/override/snapshot schema.

## Changelog

- **2026-08-04 (spec_version=15)** — Advanced Kubernetes Provider admission to v2, removed
  Provider-local NetworkPolicy lifecycle authority, and persisted exact-generation reconciliation
  evidence for Runtime Control-owned repair.
- **2026-08-03 (spec_version=14)** — Made Runner-reported current-generation workspace evidence authoritative, retained Provider mount configuration as deployment state only, and removed fixed-path and Provider-equality fallback behavior.
- **2026-07-31 (spec_version=13)** — Replaced Provider selection and execution-policy snapshots
  with exact Workspace Runtime Profile binding, immutable desired/applied configuration revisions,
  current-capability evidence, migration-only legacy conversion, and explicit recreation.
- **2026-07-28 (spec_version=12)** — Mounted the Agent Workspace and Pod-local `/tmp` into the Runner and DIND sidecar at identical paths to support ordinary Docker and Compose bind mounts.
- **2026-07-28 (spec_version=11)** — Replaced the policy Gateway with a direct Runtime-private DIND socket, collapsed Docker operations into one capability, and removed unenforceable PID, nested-container, and Profile network controls while retaining Kubernetes resource, storage, and deployment hard-cap boundaries.
- **2026-07-27 (spec_version=10)** — Added all implemented Profile network modes, Kubernetes request/limit resource semantics, and Profile-controlled PVC expansion with destructive shrink application.
- **2026-07-27 (spec_version=9)** — Removed Platform execution-policy state and made the selected Profile the complete versioned ceiling and snapshot source.
- **2026-07-27 (spec_version=7)** — Added lazy exact-Provider binding and initial policy snapshot attachment for pre-contract Runtime rows without workspace replacement.
- **2026-07-26 (spec_version=6)** — Added durable execution-policy target/applied snapshots, reset-free restrictive convergence, fixed Kubernetes topology isolation, and separate unqualified nested-engine storage.
- **2026-07-26 (spec_version=5)** — Added storage-preserving periodic convergence for desired-running Runtime workload image and configuration drift.
- **2026-07-03 (spec_version=3)** — Reflected Project-first Workspace browser ownership and registry-scoped Project root action boundary.
