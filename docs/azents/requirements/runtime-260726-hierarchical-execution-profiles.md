---
title: "Hierarchical Runtime Execution Profiles Requirements"
created: 2026-07-26
updated: 2026-07-26
tags: [runtime, provider, admin, workspace, security, containers]
document_role: primary
document_type: requirements
snapshot_id: runtime-260726
---

# Hierarchical Runtime Execution Profiles Requirements

- Snapshot: `runtime-260726`
- Document reference: `runtime-260726/REQ`

## Problem

Azents Runtime environments need optional capabilities such as nested container builds, stronger process isolation, and restricted network access. These capabilities have different security and operational costs, but the current product has no hierarchical way for Platform Administrators to define the installation-wide boundary, Workspace Administrators to narrow it, and Agent editors to select an allowed execution environment without gaining infrastructure-level control.

The first required capability is Docker-compatible nested container execution. The product model must remain suitable for later process-isolation and egress-proxy capabilities without exposing raw Kubernetes or host privileges.

## Primary Actor

Platform Administrator.

## Primary Scenario

A Platform Administrator enables validated nested-container capabilities and publishes named Runtime execution profiles within installation-wide limits. A Workspace Administrator allows a narrower subset for one Workspace and may reduce its resource, storage, and network bounds. An Agent editor selects an allowed profile and optionally adds restrictions for that Agent. After explicit application, the Agent Runtime is recreated with the effective policy and can build images or run nested containers only to the extent allowed by all three layers. The product explains the effective settings and their sources.

## Supporting Scenarios

- A Platform or Workspace Administrator removes a previously allowed capability, and affected active Runtimes automatically converge to a compliant execution environment.
- An Agent editor changes a profile or restrictive override and sees that Runtime restart is required before applying it.
- A Provider does not support a required capability or compatible version, so the profile is unavailable and provisioning fails closed rather than silently dropping the setting.
- A nested-container profile uses ephemeral engine state by default, while an explicitly permitted profile preserves bounded Runtime-owned engine state across restart.
- Future process-isolation and proxy-enforcement capabilities are added through the same hierarchy without changing the authority model.

## Goals

- Let Platform Administrators define safe installation-wide Runtime execution capabilities and named profiles.
- Let Workspace Administrators narrow Platform policy for their Workspace without granting new capability.
- Let Agent editors select an allowed profile and add only more restrictive overrides.
- Deliver granular nested-container build, run, and Compose capabilities as the first implementation.
- Keep the product policy portable across Runtime Providers while allowing Provider-specific implementation.
- Make effective policy, incompatibility, pending restart, and automatic security convergence observable.

## Non-Goals

- Allowing Administrators or Agent editors to submit arbitrary Kubernetes Pod YAML, Pod patches, sidecars, init containers, `hostPath` mounts, ServiceAccounts, or security contexts.
- Exposing a generic `privileged` switch or mounting the host Docker socket into a Runtime.
- Implementing bwrap process-isolation and egress-proxy modules in the first DinD delivery.
- Requiring every Runtime Provider to implement every execution capability in the first release.
- Hot-mutating execution settings that require Runtime infrastructure replacement.
- Redesigning Runtime Provider selection, Provider authentication, or Runner authentication.

## Requirements

### REQ-1. Hierarchical restriction authority

Runtime execution policy must resolve through Platform restriction, Workspace restriction, and Agent setting layers in that order. A lower layer may preserve or reduce authority granted by its parent but may never add, restore, or broaden authority denied by an upper layer.

**Acceptance criteria**

- A capability denied by Platform cannot be enabled by any Workspace or Agent setting.
- A capability denied for a Workspace cannot be enabled by an Agent in that Workspace.
- Resource and storage ceilings resolve to the most restrictive applicable bound.
- Network allow rules become no broader and deny rules become no narrower at lower layers.
- The product rejects an attempted privilege expansion and identifies the upper-layer restriction responsible for the rejection.

### REQ-2. Named profiles with restrictive Agent overrides

Platform Administrators must be able to publish named Runtime execution profiles. Workspace Administrators must be able to control which permitted profiles are available in their Workspace. Agent editors must select an available profile and may apply only supported restrictive overrides.

**Acceptance criteria**

- An Agent editor sees only profiles compatible with both Platform and Workspace policy.
- An Agent override can reduce resources, disable an optional capability, or add network restrictions when the selected profile supports that override.
- An Agent override cannot enable a capability, increase a ceiling, or weaken a restriction.
- The selected profile and effective restrictive overrides remain associated with the Agent independently of any one physical Runtime instance.

### REQ-3. Validated and extensible customization capabilities

Execution profiles must be composed from validated, typed customization capabilities rather than raw infrastructure configuration. The capability model must support new categories such as process isolation and egress enforcement without changing the hierarchy or granting arbitrary infrastructure access.

**Acceptance criteria**

- Every configurable field has a known type, validation rule, restriction-merging behavior, and user-facing description.
- Unsupported fields and unknown capability versions are rejected rather than ignored.
- A future bwrap-based process-isolation capability and a future proxy-based egress capability can participate in the same Platform, Workspace, and Agent resolution flow.
- Raw Provider manifests or executable customization content are not accepted through this feature.

### REQ-4. Provider compatibility and fail-closed provisioning

Execution profiles must remain product-level policy independent of a specific Provider. A Runtime may use a profile only when its bound Provider reports compatible support for every required capability.

**Acceptance criteria**

- The first complete implementation can be limited to the Kubernetes Runtime Provider.
- A Provider reports supported capabilities and compatible versions without gaining authority to expand Platform policy.
- The UI and API explain when a profile is unavailable because the selected Provider lacks support.
- Provisioning rejects an incompatible effective profile and does not create a weaker Runtime by omitting unsupported settings.

### REQ-5. Granular nested-container capabilities

The initial nested-container implementation must distinguish image building, nested container execution, and Docker Compose usage instead of exposing one unrestricted DinD boolean.

**Acceptance criteria**

- Platform policy can allow or deny image build, nested container run, and Compose independently.
- A build-only profile cannot start arbitrary nested containers.
- A development profile may allow build, run, and Compose when all upper layers permit them.
- Runtime users can use the Docker-compatible functionality granted by the effective profile without receiving host Docker access.

### REQ-6. Nested workload containment

Nested containers must remain within the Runtime's effective resource, storage, and network restrictions. Starting a nested container must not provide a path around Runtime proxy enforcement or direct-egress restrictions.

**Acceptance criteria**

- Nested workloads cannot reach a destination denied to the parent Runtime by effective policy.
- Disabling direct egress for the Runtime also prevents nested workloads from bypassing the required proxy path.
- Nested workloads cannot access Provider credentials, Runtime Control credentials other than their own permitted Runtime path, Kubernetes ServiceAccount credentials, or host infrastructure sockets.
- Resource exhaustion inside the nested engine remains bounded by limits derived from the effective profile.

### REQ-7. Explicit nested-engine storage lifecycle

Nested-engine state must be ephemeral by default. Platform policy may offer a bounded Runtime-persistent mode, and Workspace policy may prohibit it or reduce its capacity.

**Acceptance criteria**

- Ephemeral mode removes nested images, containers, and build cache when the physical Runtime is replaced.
- When persistent mode is permitted and selected, nested-engine state survives ordinary Runtime restart for the same logical Runtime.
- Runtime reset and terminal deletion remove the nested-engine state owned by that Runtime.
- The product exposes the selected storage mode and applicable capacity limit before application.
- Agent Workspace persistence remains separate from nested-engine storage lifecycle.

### REQ-8. Safe application and convergence

Agent-initiated profile or override changes must require explicit Runtime application. Platform or Workspace restriction tightening must automatically converge affected Runtimes to compliant execution environments.

**Acceptance criteria**

- An Agent setting change that affects execution infrastructure is visibly marked as requiring Runtime restart or recreation.
- The Agent editor explicitly applies the pending change before it grants new capability.
- A Platform or Workspace restriction tightening identifies affected Runtimes and automatically removes the disallowed capability through controlled lifecycle convergence.
- Automatic convergence preserves the Agent Workspace and does not invoke Runtime reset or terminal deletion.
- A failed replacement does not report the Runtime as compliant or ready.

### REQ-9. Effective-policy explainability and auditability

Administrators and Agent editors must be able to understand the effective Runtime execution policy, where each restriction originated, and why a requested profile or override is unavailable.

**Acceptance criteria**

- The effective view distinguishes Platform, Workspace, and Agent contributions.
- Rejected or reduced settings include a bounded reason identifying the governing layer.
- Profile publication, Workspace restriction changes, Agent selection changes, and automatic security convergence produce audit evidence without secret values.
- Runtime diagnostics identify the effective profile and capability versions without exposing credentials or sensitive Provider implementation data.

### REQ-10. Preserve existing Runtime trust boundaries

Execution customization must not merge Provider, Runner, Runtime Control, or host infrastructure authority.

**Acceptance criteria**

- Runtime and nested workloads receive no Provider credential.
- Runtime and nested workloads receive no host Docker socket.
- Runtime and nested workloads receive no generic unrestricted privileged mode.
- Kubernetes Runtime workloads do not receive the Provider ServiceAccount or its RBAC authority.
- Existing Provider authentication, Runner authentication, durable Provider binding, desired-generation authorization, and connection-generation fencing remain enforced.

## Fixed Constraints

- Platform policy is the absolute installation-wide authority ceiling.
- Workspace Administrators can only narrow Platform policy.
- Agent settings consist of a named profile selection plus supported restrictive overrides.
- Product policy is Provider-neutral; Kubernetes is the first implementation target.
- Customization input is typed and validated; arbitrary Pod configuration is prohibited.
- Nested-container functionality is separated into image build, container run, and Compose capabilities.
- Nested-engine storage defaults to ephemeral, with optional bounded Runtime persistence.
- Platform and Workspace security restriction changes must converge active Runtimes automatically.
- Host Docker socket mounting and a generic `privileged` Admin opt-in remain prohibited.

## Open Assumptions

- The exact built-in profile names and default profile are design-time choices as long as the hierarchy and capability behavior remain unchanged.
- The exact graceful-stop deadline and replacement scheduling behavior for automatic convergence can be selected during design.
- Nested-engine disk quota implementation and garbage-collection mechanism can vary by Provider while satisfying the observable lifecycle and capacity requirements.
- bwrap and egress-proxy implementations will be defined in later development snapshots against this same authority model.

## Confirmation

Confirmed by the requester on 2026-07-26 before ADR and design decisions began.
