---
title: "Agent Runtime Persistence"
created: 2026-05-25
tags: [backend, engine, infra]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, workspace, conversation]
code_paths:
  - python/apps/azents/src/azents/rdb/models/agent_runtime.py
  - python/apps/azents/src/azents/rdb/models/agent_runtime_add.py
  - python/apps/azents/src/azents/rdb/models/agent_runtime_removal.py
  - python/apps/azents/src/azents/rdb/models/runtime_profile.py
  - python/apps/azents/src/azents/core/runtime_profile.py
  - python/apps/azents/src/azents/repos/agent_runtime/**
  - python/apps/azents/src/azents/repos/agent_runtime_add/**
  - python/apps/azents/src/azents/repos/agent_runtime_removal/**
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
last_verified_at: 2026-08-12
spec_version: 25
---

# Agent Runtime Persistence

## Overview

Managed Agent Workspace durability is owned by the Runtime Provider backend, not by the Azents
server process and not by S3 checkpoint/restore as an event path. An Agent may be Runtime-free and
have no logical Runtime row or Workspace. When managed compute exists, the current-generation
Runner reports the effective Agent Workspace absolute path as Runtime metadata. Server file APIs,
Projects, worktrees, and prompts consume that reported path without a fixed server-side fallback.

## Runtime Profile binding and current configuration state

An Agent stores capability `none`, `managed`, or `removing` independently from one exact Workspace
Runtime Profile selection or no selection. Existing Agents were backfilled to `managed`; new Agents
default to `none` and do not create a logical Runtime. Explicit add from `none` requires an
available Profile and creates or rearms the logical row in stopped desired state.

The logical Runtime persists durable Provider routing IDs and a monotonic
`configuration_sequence` high-water mark. A one-to-one `runtime_configuration_states` row exists
only while current configuration authority remains and contains one desired slot plus an optional
applied slot. Superseded desired or applied documents are not retained as product history, and
there is no configuration archive or Profile tombstone.

The Runtime Profile resolver reads the exact Agent selection, Workspace Profile, infrastructure
Profile, Provider, and current capability as lock-free versioned snapshots. A ready desired
document records their scalar IDs, versions, digests, Agent selection version, source trace,
resolved full configuration, target desired generation, canonical digest, and complete retained
Profile v1 or Profile v2 document. These source identifiers are snapshot evidence rather than
foreign keys to mutable Profile resources. The resolver does not consult a Provider preference,
Platform default, environment default, fallback, or live Provider connection state.

Historical schema-v2 `process_containment: null` serialization is normalized away before
canonicalization; a non-null value produces a blocked desired slot rather than becoming a direct
configuration. Other unavailable source or capability results are also durable blocked slots with
bounded reasons. No Profile selection produces `unconfigured/runtime_profile_required` without
selected-Profile authority or resolved configuration. Both blocked and unconfigured desired state
preserve any older applied slot while its running incarnation remains current.

Provider connectivity is operational evidence rather than configuration identity. Disconnect and
reconnect events do not change desired status, sequence, or digest; current connection authority
separately gates lifecycle dispatch and exact Runtime operation qualification.

Resolution commits through a Runtime compare-and-set that verifies the expected sequence high-water,
desired generation, and every snapshot identity/version relationship. A materially new source,
desired generation, blocked result, or unconfigured target increments the high-water mark and
overwrites the desired slot at that positive sequence. Repeating an identical current target does
not allocate a sequence. A concurrent source change cannot attach stale state; the resolver retries
a stale write from a fresh snapshot once, and a durable Agent-selection reconcile task converges
any remaining conflict to the current authoritative selection.

The applied slot is separate physical evidence. It is overwritten only after the exact current
ready desired sequence, digest, and target generation are acknowledged by the bound Provider under
its current connection generation and by the authenticated current-generation Runner. Desired
changes therefore become visible immediately while the running incarnation may remain applied to
an older sequence or wait for explicit recreation. Returning to an earlier canonical document
still allocates a higher sequence, so old Provider or Runner evidence cannot become current again.

There is no persisted process-containment lifecycle enum, boolean, status table, or qualification
record. Product status is derived from bounded desired/applied current state, exact
sequence/digest/generation evidence, current Provider/Runner authority, and current Runner-reported
Workspace evidence.

Capability/Profile changes never reassign the Agent to another Provider or Profile. Provider or
Profile loss preserves stored selection, Provider binding, applied state, running compute, and
existing storage while blocking new create/start/restart/reset/recreate work. Historical hierarchy
conversion occurs only inside the one-way Alembic migration; runtime services do not read legacy
policy tables, snapshots, overrides, or status fallbacks.

An Owner-only exact-version Workspace Runtime Profile hard delete physically removes the Profile in
the same PostgreSQL transaction that clears a matching Workspace default and Agent selections,
advances their versions, supersedes Profile-targeted recreation, and writes affected managed
Runtimes' desired slot as higher-sequence `unconfigured/runtime_profile_required`. No fallback is
selected. Existing applied state, Provider binding, running compute, Runner-reported Workspace
path, and Agent Workspace storage remain until explicit replacement or terminal Runtime removal.

A System-Admin exact-version infrastructure Profile hard delete is permitted only when no current
Workspace Runtime Profile references the target. The transaction physically removes only the
Provider-owned Profile and terminalizes target-scoped pending or running recreation; it does not
rewrite Runtime desired or applied slots, Provider bindings, workloads, Runner-reported Workspace
paths, or Agent Workspace storage. A running Runtime may therefore retain the deleted Profile ID
inside its applied document as bounded historical evidence. That evidence is not a foreign key,
does not block deletion, and cannot authorize future create, start, restart, reset, or recreation.

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

Permanent managed Runtime removal persists one Agent-scoped operation with irreversible capability
fence, cleanup cursor/counts, interruption evidence, retry/lease state, exact target terminal-delete
generation, acknowledgement kind/time, and bounded failures. PostgreSQL is sufficient for
correctness; Redis may only accelerate wake-up.

Removal clears Session Project/worktree metadata, Runtime-only Toolkit projections, Agent Project
defaults/presets/catalog, and automatic Project policy items while preserving the automatic policy
settings row. It terminally invalidates every retained `pending` or `bound` Session folder binding.
After exact physical acknowledgement, finalization clears Profile selection, keeps shell disabled,
deletes the bounded configuration-state row, keeps the Runtime-owned sequence high-water mark,
and sets capability to `none`.

Re-add reuses a retained logical Runtime ID only after completed removal and exact acknowledgement.
It advances desired generation, allocates the next configuration sequence, writes a newly resolved
ready desired slot with no applied slot, and starts stopped with no Workspace path or applied
incarnation evidence. The Provider therefore creates a fresh empty Workspace on later start; old
Session bindings and deleted Project/worktree rows are never restored.

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

The Kubernetes Provider advertises Pod Profile schema versions 1 and 2. Both versions use direct
Runner execution. The selected Pod Profile remains the per-Runtime source of truth for resources,
storage, network policy, scheduling, identity, and optional DinD topology.

The Runtime-specific Kubernetes NetworkPolicy is the intersection of the Provider hard boundary,
the selected Pod Profile preset, and any Workspace narrowing. Required DNS and Runtime Control
traffic remains protected. Resolution uses the exact Provider's current valid capability revision,
never raw unvalidated metadata or an older historical revision. The Pod Profile separately controls
Agent Workspace PVC capacity. Expansions may apply to the existing PVC; shrink remains deferred
until an explicit reset or terminal deletion recreates storage.

Pod lifecycle observation is independent of NetworkPolicy verification history. Explicit command
reports may carry exactly one structured `network_policy` result, while watch, failover, and
lifecycle-only reports may omit it. Runtime Control never persists drift evidence, repair claims,
retry times, or completion history. A successful live-stream-correlated `OBSERVE` completion with
current `drifted` evidence may make one generation- and configuration-fenced, non-destructive
`UPDATE_CONFIGURATION` dispatch. The Reconciler locks the current Runtime row through exact
configuration lookup and queue append, so a same-generation desired-sequence replacement cannot
apply the replaced NetworkPolicy. Pending lifecycle dispatch and terminal deletion prevent repair.
Stale evidence cannot dispatch; a reconnect, stream/control restart, lost completion, or dispatch
failure is discarded and can retry only after a later periodic `OBSERVE`. Unsupported evidence kinds
reject the actionable handoff without changing Provider lifecycle authority. The current schema
removes the obsolete reconciliation enum, columns, foreign key, and index through successor
Alembic revision `d51acb332a07`; no Runtime row persists repair state.

## Docker Provider v1

Docker Provider v1 assumes one stable Docker host. For each Runtime it creates a host directory and
bind-mounts it into the Runner container at its configured Runner home path. The host directory is
the event persistence source.

The Provider protocol remains Docker Provider v1 while the selected infrastructure Profile may be
schema v1 or v2. Both versions use direct Runner execution. The durable host Workspace directory
remains mounted at the same Agent path, and the Provider-owned temporary directory is scoped to the
Runtime incarnation.

Stop/restart/recover and ordinary recreation may remove/recreate containers, but must keep the host
directory. Reset may delete or replace the host directory according to the reset command. Terminal
delete removes the container, Workspace directory, and Provider-owned ephemeral directories.

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
- Profile tests prove v1/v2 direct preservation, canonical current-state identity, historical null-field
  normalization, and active containment rejection.
- Docker and Kubernetes Provider tests prove Workspace persistence and ephemeral-state clearing on
  recreation.
- Schema and migration searches prove no containment application or availability state is
  persisted.
- Migration tests prove exact legacy effective-selection conversion and final absence of obsolete
  policy/override/snapshot schema.

## Changelog

- **2026-08-12 (spec_version=25)** — Added infrastructure Profile hard deletion with current
  Workspace-reference blocking, applied-only Runtime evidence retention, recreation
  terminalization, and no Runtime or Agent Workspace mutation.
- **2026-08-11 (spec_version=24)** — Replaced configuration revision history with one bounded
  desired/applied current-state row and Runtime-owned sequence high-water, added exact
  sequence/digest/generation promotion and cleanup, and documented Owner hard delete without
  fallback or running Workspace disruption.
- **2026-08-11 (spec_version=23)** — Removed process-containment selection and derived status from
  persisted Runtime configuration while retaining historical null-field normalization and
  fail-closed rejection of active values.
- **2026-08-11 (spec_version=22)** — Removed the Kubernetes process-containment deployment feature
  flag and made Pod Profile schema v2 a permanent Provider capability.
- **2026-08-10 (spec_version=21)** — Made AgentRuntime optional, added durable add/removal
  transition persistence and bounded cleanup evidence, preserved the empty automatic Project policy
  authority, and defined acknowledged higher-generation re-add with a fresh Workspace.

- **2026-08-09 (spec_version=20)** — Removed live Provider connectivity from immutable
  configuration revision identity while retaining connection-gated lifecycle dispatch and
  operation qualification.
- **2026-08-09 (spec_version=19)** — Added persisted Profile v1/v2 containment choice, derived
  containment status without new lifecycle state, Provider-specific temporary-storage lifetimes,
  and Workspace-preserving containment adoption and rollback.
- **2026-08-07 (spec_version=18)** — Made Runtime Profile source reads lock-free and fenced the
  desired pointer attachment by exact versioned source evidence, Runtime generation, and durable
  reconcile convergence after a stale attachment.
- **2026-08-05 (spec_version=17)** — Serialized the bounded repair target with the Runtime row
  through exact configuration lookup and Provider append, and preserved migration history through
  successor schema removal.
- **2026-08-05 (spec_version=16)** — Removed durable Runtime drift/repair projection and made a
  current correlated `OBSERVE` completion the sole one-shot NetworkPolicy repair handoff; periodic
  observation is the retry boundary.
- **2026-08-04 (spec_version=15)** — Advanced Kubernetes Provider admission to v2 and removed
  Provider-local NetworkPolicy lifecycle authority.
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
