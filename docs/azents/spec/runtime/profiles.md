---
title: "Runtime capability and profiles"
created: 2026-11-04
tags: [wiki]
---

# Runtime capability and profiles

Connects an Agent’s managed-compute capability and exact profile selection with Workspace profile management. Model candidate profiles are unrelated and live in model selection.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Agent](../domain/agent.md)
- [Runtime Providers](../domain/runtime-provider.md)
- [Runtime persistence](../flow/agent-runtime-persistence.md)
- [Workspaces and membership](../domain/workspace.md)

## Runtime Profile selection

Each Agent stores a Runtime capability independently from its optional exact Workspace Runtime
Profile selection. Agents do not store a Provider preference, infrastructure override, or
restrictive execution-policy overlay.

New Agent creation defaults to `runtime_capability=none`. An omitted or explicit-null Runtime Profile
does not consult or copy the Workspace default and creates no logical `AgentRuntime`. Supplying an
explicit available Workspace Runtime Profile grants `managed` capability in the creation
transaction. The Workspace default remains picker assistance only. Existing Agents were migrated to
`managed` without changing their stored Profile selection, so `managed` with a null Profile is the
valid managed-unconfigured state.

Only the dedicated add action changes `none` to `managed`, and only the irreversible remove action
changes `managed` to `removing`. Generic Agent patch cannot change capability. While managed,
`runtime_profile_id` remains a partial update: omission leaves it unchanged, explicit null clears
the selection, and a non-null replacement must identify a Profile in the same Workspace. Selection
changes enqueue authoritative Runtime configuration reconciliation; there is no Agent Apply action.
An unavailable selected Profile remains visible and stored, and the server never substitutes
another Profile or Provider.

Permanent Profile deletion and its atomic effects are defined once under
[Workspace profile management](#workspace-profile-management). Removing a selection
never chooses a fallback. Profile-dependent lifecycle work must wait for an explicit
replacement; ordinary operations on an already-ready Runner are a distinct admission
path and may use retained applied configuration. They still validate current Agent
capability/version, desired generation, applied sequence/digest and Workspace path.
See the [ordinary operation admission repository](../../../../python/apps/azents/src/azents/repos/runtime_operation_admission.py)
for that exact distinction; Terminal retains its additional current-Profile policy
requirements.

## Adding and removing managed capability

`GET /agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime` is read-only and never
ensures, configures, or starts a Runtime. It returns the Agent capability/version, Profile
selection/version and availability, optional logical/physical Runtime state, privacy-safe aggregate
removal impact, optional durable removal progress, and server-computed actions.

`POST .../runtime/add` requires Agent-management permission, expected capability and Profile
selection versions, an explicit available Workspace Runtime Profile, and an idempotency key. It
creates a stopped logical Runtime when none exists or rearms the retained terminally deleted logical
identity at a higher desired generation after exact deletion acknowledgement. Add does not allocate
active compute.

`POST .../runtime/remove` requires the same management boundary, optimistic versions, an idempotency
key, and semantic `confirmed=true`. The commit changes capability to `removing` and immediately
fences ordinary Agent work. The durable coordinator interrupts Team and private User Session trees,
clears Runtime-owned product state, waits for exact physical terminal-delete acknowledgement, then
finalizes capability to `none`. The operation cannot be cancelled, and add remains unavailable
until completion.

## Workspace profile management

A Workspace owns a catalog of complete Runtime choices. Each Workspace Runtime Profile binds one
exact durable Runtime Provider resource to one Provider-owned infrastructure Profile and adds only
Workspace-owned policy that the selected infrastructure contract permits. The infrastructure
Profile must belong to that exact Provider and match its Provider kind, and the Workspace Runtime
Profile cannot be read or mutated through another Workspace.

Infrastructure and Workspace Runtime Profiles each store a default-true
`terminal_enabled` policy. Infrastructure policy is the Provider-owned ceiling;
Workspace policy may narrow but cannot override a false infrastructure value. Agent
policy is evaluated separately at Terminal admission. Profile Terminal-only changes
publish source invalidation for active browser Terminals but do not change Runtime
configuration digest, desired generation, or recreation status.

Terminal admission also requires the Agent's exact current Workspace Profile and
infrastructure Profile chain to remain active and mutually consistent. After that
policy resolves, the selected Session must have a `bound` working folder validated
against the current Runtime capability version, desired generation, Runner generation,
applied configuration, and Runner-reported Agent Workspace path. Missing or stale
Profile or working-folder authority produces a fail-closed unavailable projection; it
never selects another Profile, falls back to a fixed directory, or starts the Runtime.

The current Workspace policy surface is restrictive-only network authority for Kubernetes
Profiles. Policy v1 remains direct-only CIDR narrowing. Policy v2 may preserve or reduce the
Provider mode through `direct` → `proxy_required` → `no_network`, intersect inherited CIDRs, reduce
an unrestricted proxy policy to an allowlist, narrow an inherited allowlist, and add final domain
denials. It cannot restore direct access, expand CIDRs or domains, remove inherited denials, or
restore a denied protocol. Docker Profiles use Policy v1 with no Workspace network restriction and
reject strict policy rather than claiming false parity.

Profile create, complete replacement, default selection, and scoped recreation require
`RUNTIME_PROFILES_WRITE`; reads require `RUNTIME_PROFILES_READ`. Owners and Managers retain these
ordinary management permissions. Permanent deletion requires the distinct
`RUNTIME_PROFILES_DELETE` permission granted only to the Workspace Owner. Replacement and deletion
use an exact expected Profile version. Lifecycle can make a Profile unavailable without deleting
it, its Agent selections, or its Runtime references. Availability is computed from the exact
Provider lifecycle/connection/current capability, infrastructure Profile compatibility, and
Workspace Profile state. No arbitrary substitute is selected.

Infrastructure and Workspace Runtime Profile responses expose typed Profile and Policy schemas
without a derived process-containment projection. Admin Kubernetes create/edit supports Profile v3
network modes, CIDR/domain policy, and independent strict-capability attestations; Docker remains
Profile v1/v2 direct-only. Workspace create/edit selects Policy v1 for Docker and Policy v2 for
Kubernetes, constrains available options by the selected parent authority, and explains effective
protocol/trust limitations. Historical schema-v2 documents with `process_containment: null` remain
readable, while non-null removed values are rejected rather than translated to direct execution.

Each Workspace also stores a nullable default Runtime Profile and an optimistic default version.
The default is picker assistance only; omitting Runtime selection on Agent creation produces a
Runtime-free Agent and does not copy the default. Changing or clearing the default does not modify
existing Agents.

`DELETE /runtime-profile/v1/workspaces/{handle}/profiles/{profile_id}` permanently removes one
Profile using `expected_version`. In one PostgreSQL transaction it clears a matching Workspace
default and advances the default version, clears every matching Agent selection and advances each
selection version, supersedes active recreation operations for the Profile, writes affected
managed Runtimes' desired current state as `unconfigured/runtime_profile_required` at a higher
configuration sequence, and deletes the Profile row. The committed response reports whether the
default was cleared plus bounded counts for cleared Agents, affected running Runtimes, and
superseded recreation operations. A stale version conflicts, a missing or cross-Workspace Profile
is not found, and any failure rolls the whole operation back.

Deletion never selects a fallback Workspace default, Provider default, or other Profile. Affected
managed Agents remain managed but unconfigured and expose `profile_required` until an authorized
Agent manager explicitly selects a replacement. Already running Runtimes keep their current
Provider binding and applied configuration, and Agent Workspace storage is neither reset nor
deleted. Profile-dependent create, start, restart, reset, and recreate operations remain
unavailable. A ready current-generation Runner may continue ordinary operations from the retained
applied configuration; stop, observation, and terminal Runtime removal remain available where
their normal lifecycle authority permits them. Selecting and applying a replacement remains the
recovery path for future host lifecycle work and preserves Workspace storage.

Parent Profile changes enqueue authoritative current desired-configuration-state reconciliation
for affected Agents. Kubernetes CIDR-only and proxy-owned policy/artifact changes may be adopted in
place after exact sequence, digest, generation, aggregate Provider enforcement, and ordinary Runner
evidence. Mode, Runtime trust, mandatory-host mapping, PodSpec, PVC, and Docker changes remain
`waiting_for_recreation` until an authorized actor creates a durable scoped recreation operation.
Recreation snapshots target IDs and versions plus current configuration authority, uses bounded
concurrency, reports progress and bounded failures, skips stale/superseded targets, and preserves
Agent Workspace data. Desired/applied Runtime status projects the effective network mode and
bounded limitations without exposing Kubernetes resources, CA material, or credentials. No Agent
Apply action exists.

System Administrators have a separate read-only Admin detail for one exact Workspace Runtime
Profile. It resolves by Workspace handle and Profile ID, returns Workspace and Profile identity,
policy, selected Provider and infrastructure Profile, lifecycle/version metadata, selected-Agent
count, and running-Runtime count, and returns not found for a mismatched pair. This inspection path
does not require Workspace membership and exposes no Workspace mutation; instance-wide System Admin
authority and customer Workspace roles remain separate.

## API route entrypoints

- `/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/add`
- `/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/remove`
- `/runtime-profile/v1/workspaces/{handle}/default`
- `/runtime-profile/v1/workspaces/{handle}/infrastructure-profiles`
- `/runtime-profile/v1/workspaces/{handle}/profiles/{profile_id}/recreation-operations`
- `/runtime-profile/v1/workspaces/{handle}/recreation-operations/{operation_id}`

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/core/runtime_admission.py`](../../../../python/apps/azents/src/azents/core/runtime_admission.py)
- [`python/apps/azents/src/azents/services/runtime_profile_workspace`](../../../../python/apps/azents/src/azents/services/runtime_profile_workspace)
- [`python/apps/azents/src/azents/services/runtime_profile_reconciliation`](../../../../python/apps/azents/src/azents/services/runtime_profile_reconciliation)
