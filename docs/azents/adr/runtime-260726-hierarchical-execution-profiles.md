---
title: "Hierarchical Runtime Execution Profiles"
created: 2026-07-26
tags: [runtime, provider, workspace, security, containers, architecture]
document_role: primary
document_type: adr
snapshot_id: runtime-260726
---

# Hierarchical Runtime Execution Profiles

- Snapshot: `runtime-260726`
- Requirements: [`runtime-260726/REQ`](../requirements/runtime-260726-hierarchical-execution-profiles.md)

## Context

Azents already has immutable Runtime Provider contract and configuration revisions, Agent-scoped Provider overrides, immutable Runtime policy snapshots, exact Provider binding, and desired-generation fencing. These foundations describe Provider eligibility and Provider-scoped configuration, but they do not model a Platform-to-Workspace-to-Agent execution-policy hierarchy, named product-level profiles, typed capability merge semantics, or Provider acknowledgement of an applied execution policy.

The Kubernetes Provider currently translates static Provider process configuration into one Runner Pod and one Agent Workspace PVC. It does not receive a resolved execution-policy snapshot, provision nested-container infrastructure, separate nested-engine storage from the Agent Workspace, or mediate Docker-compatible operations by capability.

Workspace membership and system administration are separate authorization domains. Platform Runtime Provider management is System Admin-only, while Agent and Workspace configuration live in the Public API and main Web application. Existing Runtime policy snapshot source tracing and generation state provide a reusable basis for effective-policy explanation and safe application, but the new hierarchy requires server-side authorization, optimistic mutation control, and metadata-only audit evidence at every management layer.

## Confirmed Directions

The following directions are fixed by `runtime-260726/REQ` and are not reopened as ADR alternatives:

- Platform policy is the installation-wide authority ceiling; Workspace and Agent layers are restrictive only.
- Agent configuration is a named profile selection plus supported restrictive overrides.
- Execution capability definitions are typed, validated, Provider-neutral product policy; Kubernetes is the first implementation Provider.
- Image build, nested container run, and Compose are separate capabilities.
- Nested-engine state is ephemeral by default, with an optionally permitted bounded Runtime-persistent mode.
- Agent changes require explicit application, while Platform or Workspace security tightening automatically converges affected Runtimes.
- Raw Provider manifests, host Docker sockets, generic privileged opt-in, and credential-boundary weakening remain prohibited.

## Decision Backlog

The decisions are discussed in this dependency order. Each accepted decision will be appended under `## Decisions` before the next point begins.

1. **Accepted — execution-policy ownership and persistence model** — use a first-class product policy domain with mutable current Platform, Workspace, profile, and Agent records; retain immutable history only in effective Runtime policy snapshots and existing Provider contract/configuration revisions.
2. **Accepted — Profile identity and change propagation** — use stable mutable Profile identity; automatically converge restrictive changes and require explicit Agent application before authority-expanding changes take effect.
3. **Accepted — Workspace governance authority and surface** — allow Workspace `OWNER` and `MANAGER` roles to manage Workspace execution restrictions through the Public API and main Web surface; keep Agent-admin and System Admin authority separate.
4. **Accepted — restrictive resolution and invalidation semantics** — deterministically narrow supported fields across layers; preserve the Agent selection but stop the Runtime and block provisioning when the selected Profile becomes unsatisfiable, without fallback.
5. **Accepted — Provider capability negotiation and Runtime Control contract** — Azents owns versioned module semantics; Providers declare compatible support and must acknowledge the exact effective snapshot digest and desired generation applied.
6. **Accepted — pending application and automatic convergence state model** — keep mutable Agent intent separate from Runtime target/applied snapshots; create targets only for explicit Agent application or automatic administrative tightening and verify them through desired-generation fencing.
7. **Accepted — nested-container enforcement architecture** — start with a Provider-owned fixed privileged Docker Engine sidecar behind an unprivileged policy gateway; keep Runner and nested workloads unprivileged and defer a User Namespace/rootless engine as a compatible future Provider option.
8. **Accepted — nested workload network containment** — make Kubernetes Pod NetworkPolicy the final egress authority and use the policy gateway to prohibit Docker networking modes that could bypass the Provider-generated Runtime network path.
9. **Accepted — nested-engine storage topology and lifecycle** — use ephemeral engine-only storage by default and expose separate Runtime-persistent engine PVCs only when the Provider can enforce the resolved capacity bound and lifecycle.
10. **Accepted — existing-Agent migration and safe baseline** — attach existing and new Agents to a reserved non-expanding `system-standard` Profile without granting capability or forcing baseline-equivalent active Runtimes to restart.
11. **Accepted — mutation concurrency, audit, and explainability contract** — use expected current versions for conflicts, append-only metadata audit events for management actions, and immutable Runtime Policy Snapshots for applied history and per-layer explanation.

## Decisions

### runtime-260726/ADR-D1. Own execution policy as a first-class product domain without per-edit policy revisions

**Affects:** `runtime-260726/REQ-1`, `runtime-260726/REQ-2`, `runtime-260726/REQ-3`, `runtime-260726/REQ-4`, `runtime-260726/REQ-9`

Azents owns a Provider-neutral execution-policy domain for the typed capability catalog, current Platform limits, named profiles, current Workspace restrictions, and current Agent selection and restrictive overrides. Runtime Provider configuration does not become the authority for this product policy. A Provider contract only declares the capability module versions and enforcement features that the Provider can implement.

Platform, profile, Workspace, and Agent policy records are mutable current-state resources with monotonic versions for optimistic mutation control. Ordinary policy edits do not create immutable policy-revision rows. Existing immutable Provider contract and configuration revisions remain unchanged because they serve the separate Provider compatibility and configuration lifecycle.

Each policy application or automatic security convergence produces an immutable effective `RuntimePolicySnapshot` containing the resolved policy, source versions, digest, target desired generation, and application evidence. The snapshot, rather than a revision table for every administrative edit, is the durable historical record of what a Runtime was instructed to enforce.

**Rejected:** Extending Provider configuration into the product-policy authority would couple named profiles and hierarchy semantics to one Provider. Creating immutable revisions for every Platform, Workspace, profile, and Agent mutation would add lifecycle and storage complexity beyond the required current-state management and applied-policy audit contract. Generic untyped JSON would not provide safe merge or compatibility validation.

### runtime-260726/ADR-D2. Use stable mutable Profiles with direction-sensitive propagation

**Affects:** `runtime-260726/REQ-2`, `runtime-260726/REQ-8`, `runtime-260726/REQ-9`

Each named execution Profile has a stable product identity and mutable current content. An Agent selection references the Profile identity rather than an immutable Profile revision. Profile names and descriptions update immediately without Runtime application.

When a Profile change removes capability or narrows a bound, affected active Runtimes automatically converge to a newly resolved compliant snapshot. When a change adds capability or broadens a bound, existing Runtimes retain their applied snapshot and expose the newly resolved state as pending until an Agent editor explicitly applies it. A single Profile edit that contains both directions is treated as security tightening for automatic removal, while every authority expansion remains pending.

Retirement and complete upper-layer invalidation behavior are decided separately with the restrictive-resolution contract. No Profile mutation silently grants additional Runtime authority.

**Rejected:** Automatically applying both expansion and restriction would let a Platform edit grant new Agent authority without Agent application. Making used Profiles immutable and requiring clone-and-reselect would recreate manual revision management and add avoidable operational overhead.

### runtime-260726/ADR-D3. Let Workspace Owners and Managers govern Workspace execution restrictions

**Affects:** `runtime-260726/REQ-1`, `runtime-260726/REQ-2`, `runtime-260726/REQ-9`, `runtime-260726/REQ-10`

Workspace `OWNER` and `MANAGER` roles may read and mutate the Workspace execution-profile allow-list and restrictive bounds. Workspace `MEMBER` may read the safe policy and effective availability projections but may not mutate Workspace policy. Authorization is enforced by the Public API and service layer; client-side visibility is not an authorization boundary.

Agent administrators retain authority over Profile selection and restrictive overrides only for Agents they administer, subject to existing Workspace-owner behavior. They cannot mutate Workspace policy. A System Admin manages Platform execution policy through the Admin API and Admin Web, but System Admin status alone does not grant Workspace policy authority without Workspace membership.

Workspace policy management belongs to the main Web Workspace administration surface rather than the System Admin application. Platform, Workspace, and Agent writes remain distinct authenticated operations even when one user holds multiple roles.

**Rejected:** Owner-only management would unnecessarily centralize routine Workspace security administration. A new dedicated Workspace role or permission assignment system would broaden this snapshot beyond the established role model. UI-only role gating would permit unauthorized direct API writes.

### runtime-260726/ADR-D4. Narrow deterministically and stop when the selected Profile is unsatisfiable

**Affects:** `runtime-260726/REQ-1`, `runtime-260726/REQ-2`, `runtime-260726/REQ-4`, `runtime-260726/REQ-6`, `runtime-260726/REQ-8`, `runtime-260726/REQ-9`

The resolver applies module-owned monotone merge operators in Platform, Workspace, Profile, and Agent order. Boolean authority uses logical intersection, numeric ceilings use the lowest bound, allow sets intersect, deny sets union, and persistence may narrow from bounded persistent to ephemeral. Module dependencies are revalidated after every layer. Unknown fields, unknown module versions, and unsatisfied dependencies fail closed.

When upper-layer policy can produce a valid narrower form of the selected Profile, the system creates and automatically applies a compliant effective snapshot. The stable Agent Profile selection remains unchanged and the effective view identifies every reduction and its governing layer.

When the selected Profile is prohibited as a whole, a required capability becomes unavailable, or the resolved module set is unsatisfiable, the system preserves the Agent selection as unavailable, safely stops the Runtime, and blocks start or provisioning until an authorized editor selects or restores a valid Profile. It does not choose another Profile or silently omit a required capability. Stop and convergence preserve the Agent Workspace and any separately owned persistent nested-engine storage.

**Rejected:** Automatic baseline substitution would run an execution environment the Agent editor did not select and could hide the governing incompatibility. Retaining a noncompliant Runtime until manual action would violate automatic security convergence.

### runtime-260726/ADR-D5. Keep capability semantics in Azents and require exact Provider application evidence

**Affects:** `runtime-260726/REQ-3`, `runtime-260726/REQ-4`, `runtime-260726/REQ-6`, `runtime-260726/REQ-8`, `runtime-260726/REQ-9`, `runtime-260726/REQ-10`

Azents owns a versioned catalog of typed execution capability modules, including each module's validation, dependency, restriction merge, user-facing explanation, and canonical serialization semantics. Providers cannot introduce product policy fields or redefine their authority meaning through a dynamic schema.

A Provider contract declares the module identifiers and compatible versions it implements, bounded Provider enforcement limits, and supported application behavior. Provider compatibility is checked after hierarchical policy resolution and before provisioning or replacement. Unknown, incompatible, or incomplete support fails closed.

Runtime Control sends the immutable Runtime Policy Snapshot ID and digest, target desired generation, and canonical validated effective module values. Secret material, when a future module requires it, is separated from the non-secret policy projection and limited to the execution boundary that needs it; Provider, Runner, sandbox-control, and nested-workload credentials remain distinct.

Provider observation reports the exact snapshot ID, digest, and desired generation that its Runtime resources enforce. Control marks a Runtime compliant and ready only when authoritative Provider and Runner evidence matches the current target. A report that omits or mismatches policy evidence remains pending or divergent and cannot be treated as a weaker successful application.

**Rejected:** Provider-defined dynamic schemas would let Provider implementations redefine product security semantics. Free-form capability strings would not prove field-level compatibility, merge behavior, or applied policy identity.

### runtime-260726/ADR-D6. Separate mutable Agent intent from target and applied Runtime snapshots

**Affects:** `runtime-260726/REQ-2`, `runtime-260726/REQ-8`, `runtime-260726/REQ-9`, `runtime-260726/REQ-10`

The Agent's current Profile selection and restrictive overrides are mutable intent. Saving Agent intent does not itself dispatch Runtime infrastructure changes. The service compares freshly resolved intent with the Runtime's applied snapshot and projects whether explicit application is required. Metadata-only changes that do not alter canonical effective execution policy do not create a target or require replacement.

An Agent Apply operation resolves and validates the current intent, creates one immutable target Runtime Policy Snapshot, advances the desired generation, fences the previous generation, and requests Provider convergence. Platform or Workspace security tightening performs the same target creation and convergence automatically without Agent approval. Administrative authority expansion remains unapplied until an Agent editor explicitly applies the current intent.

Provider and Runner evidence promotes the target snapshot to applied only when snapshot identity, digest, Provider binding, and desired generation all match. A failed or mismatched replacement remains pending or divergent and is not reported ready or compliant. Security tightening stops or fences the old noncompliant generation before it can retain authority. Convergence preserves Agent Workspace storage and does not invoke reset or terminal deletion.

This state model uses application snapshots as the historical evidence boundary and does not introduce a deployment or revision resource for every settings edit.

**Rejected:** Applying every settings save immediately would grant authority without explicit Agent application. A separate deployment/revision object for each edit would duplicate the snapshot and desired-generation lifecycle without a requirement-level benefit.

### runtime-260726/ADR-D7. Start with a fixed privileged engine behind an unprivileged policy gateway

**Affects:** `runtime-260726/REQ-4`, `runtime-260726/REQ-5`, `runtime-260726/REQ-6`, `runtime-260726/REQ-7`, `runtime-260726/REQ-10`

The initial Kubernetes implementation uses one Provider-generated Runtime Pod containing an unprivileged Runner, an unprivileged Azents container policy gateway, and a fixed privileged Docker Engine sidecar. The Runner mounts only the gateway Unix socket. The private engine socket is mounted only between the gateway and engine and is never exposed to the Runner, nested workloads, Agent Workspace, or user-configurable paths.

The gateway is the mandatory Docker-compatible authority boundary. It independently authorizes image-build, container-run, and Compose operations and rejects or rewrites resource, storage, mount, device, capability, namespace, security, and network options outside the effective Runtime Policy Snapshot. Nested workloads cannot request privileged mode, host paths or devices, host namespaces, arbitrary added capabilities, or direct engine access.

The Provider owns immutable engine and gateway image references, generated container names and paths, security context, volumes, and lifecycle translation. Product policy does not expose a privileged toggle, sidecar definition, image override, Pod patch, or raw infrastructure configuration. The engine receives no Kubernetes ServiceAccount token, Provider credential, or Runtime Control credential. Its privileged authority is an implementation risk explicitly accepted for the initial Provider implementation, not authority delegated to Agent editors or nested workloads.

Clusters may disable this capability when their admission policy rejects the fixed engine topology. Compatible nodes may be Provider-labeled for scheduling, but users cannot submit node selectors. A future Kubernetes User Namespace/rootless engine may implement the same module and gateway contract on qualified clusters without changing Profile or Agent policy semantics.

**Rejected:** Giving the Runner the engine socket would make build-only enforcement impossible and grant unrestricted Docker API authority. A generic privileged Profile setting or host Docker socket would violate the confirmed trust boundary. Kubernetes-native Docker/Compose translation and a remote multi-tenant engine pool add substantially more first-release scope. Requiring User Namespace/rootless DinD initially would exclude otherwise supported clusters and is deferred as an optional Provider implementation.

### runtime-260726/ADR-D8. Enforce egress at the Pod boundary and constrain Docker networking at the gateway

**Affects:** `runtime-260726/REQ-1`, `runtime-260726/REQ-3`, `runtime-260726/REQ-6`, `runtime-260726/REQ-8`, `runtime-260726/REQ-9`, `runtime-260726/REQ-10`

Kubernetes NetworkPolicy at the Runtime Pod boundary is the authoritative nested-workload egress control. The common Runtime policy permits only mandatory platform destinations such as DNS and Runtime Control. Provider-generated Runtime-specific policies add the destinations allowed by the effective execution policy, including direct egress or a required proxy endpoint. A no-network policy adds no optional egress.

The existing broad namespace Runtime egress rule must not continue to select Profile-managed Runtimes because Kubernetes allow rules are additive. The Provider creates, labels, observes, replaces, and deletes Runtime-specific NetworkPolicy resources under desired-generation and policy-digest fencing. Users cannot submit raw NetworkPolicy, CIDR patches, namespace selectors, or Provider resource names.

The container policy gateway allows only Provider-owned internal Docker networks and rejects host networking, host or external namespace sharing, macvlan or ipvlan, arbitrary network drivers or plugins, cross-Runtime attachment, unauthorized port publication, and DNS or proxy options that broaden effective policy. All permitted nested traffic leaves through the Runtime Pod network boundary. Proxy environment or Docker configuration improves compatibility but is not the security enforcement boundary.

A Runtime is not compliant until the Provider observes the intended Pod and NetworkPolicy generation and reports matching snapshot evidence. Automatic restriction convergence fences the old Runtime network authority before the replacement is declared ready.

**Rejected:** Gateway-only enforcement would make an API validation defect sufficient to bypass egress policy. Disabling all nested networking would prevent ordinary build, package, service, and Compose use cases required by enabled Profiles.

### runtime-260726/ADR-D9. Separate engine storage and advertise only enforceable persistence modes

**Affects:** `runtime-260726/REQ-1`, `runtime-260726/REQ-3`, `runtime-260726/REQ-6`, `runtime-260726/REQ-7`, `runtime-260726/REQ-8`, `runtime-260726/REQ-9`

Nested-engine image layers, containers, volumes, and build cache never use the Agent Workspace volume. The default ephemeral mode mounts an engine-only ephemeral volume into the engine container, applies the resolved ephemeral-storage envelope, and removes the state whenever the physical Runtime Pod is replaced. Runner and gateway access to engine state is limited to the separate gateway and engine socket paths required by their protocol.

A Provider may advertise bounded Runtime-persistent engine storage only when it can enforce the resolved capacity and lifecycle. Persistent mode uses a separate engine PVC owned by the logical Runtime. Stop, restart, recovery, and compliant replacement preserve that PVC. Reset and terminal deletion remove it independently of the Agent Workspace PVC. Platform and Workspace policy may prohibit persistent mode or reduce its maximum capacity; Agent settings may only select an allowed mode and reduce capacity.

Provider compatibility identifies supported storage modes, maximum enforceable capacities, and quota behavior. A Profile requiring persistent mode is unavailable when the bound Provider or configured storage backend cannot prove the required bound. Requested PVC size without enforceable capacity is not sufficient evidence.

The initial `home` Kubernetes deployment advertises ephemeral engine storage only because its current local-path storage does not yet provide verified bounded persistent engine capacity. The product contract retains persistent mode for Providers and clusters with a qualified storage backend.

**Rejected:** Treating a local-path request size as a proven hard quota could allow node-disk exhaustion. Storing engine data under the Agent Workspace would mix user data and engine lifecycle, and making every engine persistent would violate the ephemeral default and retain unnecessary authority and state.

### runtime-260726/ADR-D10. Migrate every Agent to a reserved non-expanding Standard Profile

**Affects:** `runtime-260726/REQ-2`, `runtime-260726/REQ-5`, `runtime-260726/REQ-8`, `runtime-260726/REQ-9`, `runtime-260726/REQ-10`

Azents provides the reserved stable Profile identity `system-standard`. Its product-owned capability content represents the existing ordinary Runtime environment: optional execution modules are disabled and no nested-engine storage exists. The Profile cannot be deleted, retired, or broadened. Platform and Workspace restrictions continue to apply, and display metadata may be localized without changing its stable identity.

Migration explicitly assigns existing Agents to `system-standard`; a null selection does not remain as a permanent legacy meaning. New Agents also begin with `system-standard`. Creating or publishing an authority-bearing Profile never changes that default or grants capability automatically. An Agent editor must select another allowed Profile and explicitly apply it.

Migration does not replace active Runtimes whose observed topology is baseline-equivalent. Existing single-Runner Runtimes receive no DinD authority and preserve their Workspace. Provider observation may confirm baseline equivalence, and the next natural start or restart attaches a fully acknowledged Standard policy snapshot. Any observed deviation from the baseline follows normal divergent or convergence handling rather than being trusted by migration.

**Rejected:** Applying the current Platform default could grant new authority or trigger a fleet-wide replacement. Retaining null as an indefinite legacy Profile would require permanent special cases in policy resolution and explanation. Replacing every baseline-equivalent Runtime during migration would add rollout risk without changing effective authority.

### runtime-260726/ADR-D11. Separate optimistic concurrency, management audit, and applied history

**Affects:** `runtime-260726/REQ-1`, `runtime-260726/REQ-2`, `runtime-260726/REQ-3`, `runtime-260726/REQ-8`, `runtime-260726/REQ-9`, `runtime-260726/REQ-10`

Each mutable Platform policy, Profile, Workspace policy, and Agent intent resource has a monotonic current version. Management writes include the caller's expected version and atomically reject stale changes without partial mutation. The version is a concurrency token and source-trace input, not an immutable policy revision or rollback object.

Execution-policy management and convergence append metadata-only audit events that identify the actor or system authority, management layer, target identity, before and after canonical digests, changed module paths, authority-expansion or restriction classification, bounded impact counts, reason code, correlation identity, and outcome. Audit events contain no secret values, credentials, projected tokens, or complete sensitive configuration and are not used as a policy reconstruction source.

Runtime Policy Snapshots remain the immutable applied-history boundary. Each snapshot identifies its Profile and Platform, Profile, Workspace, and Agent source versions; canonical effective modules; governing source for each value; reduction and rejection reason codes; Provider capability versions; target and applied digest; and desired generation. Public and Admin projections distinguish current configured intent, pending target or incompatibility, and Provider-acknowledged applied policy.

**Rejected:** Last-write-wins mutation would allow administrators to silently overwrite one another and would weaken audit correlation. Immutable revision resources for every settings write would duplicate the accepted current-state and application-snapshot model.

## Decision Summary

The accepted decisions establish a Provider-neutral first-class execution-policy domain with mutable current policy, stable Profiles, restrictive hierarchical resolution, exact Provider compatibility and application evidence, explicit Agent application, automatic security convergence, a gateway-mediated privileged DinD engine for the initial Kubernetes implementation, Pod-boundary network enforcement, separate bounded engine storage, safe Standard migration, and separated concurrency, audit, and applied-history responsibilities. No additional requester-level ADR decisions remain before the complete Design and feasibility validation.
