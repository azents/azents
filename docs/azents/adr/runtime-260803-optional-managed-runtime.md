---
title: "Optional Managed Runtime for Agents"
created: 2026-08-03
tags: [agent, runtime, workspace, architecture, security]
document_role: primary
document_type: adr
snapshot_id: runtime-260803
---

# runtime-260803/ADR: Optional Managed Runtime for Agents

- Snapshot: `runtime-260803`
- Requirements: [`runtime-260803/REQ`](../requirements/runtime-260803-optional-managed-runtime.md)
- Decision mode: Collaborative
- Decision owner: Requester

## Context

The confirmed Requirements make a managed Runtime optional at Agent scope. New Agents default to no Runtime, existing Agents preserve their current Runtime capability, administrators can explicitly add a lazily provisioned Runtime, and permanent removal deletes Runtime-owned Workspace state while preserving non-Runtime Agent state.

Current behavior does not have a distinct Runtime-free Agent state. A null Runtime Profile means an unconfigured Runtime-capable Agent, input admission ensures a logical Runtime row, Runtime API reads resolve a Profile, shell enablement controls only the built-in Runtime Toolkit, and several Toolkit, Skill, Project, Workspace, and credential paths carry separate Runtime assumptions.

This ADR records the remaining material ownership, lifecycle, identity, capability-authority, API, and Workspace UX decisions required by `runtime-260803/REQ`.

## Decision Status

- **D1 — Runtime capability and removal-state authority:** accepted
- **D2 — Removal cancellation boundary:** accepted
- **D3 — Runtime identity after removal and re-addition:** accepted
- **D4 — Runtime-required capability authority:** accepted
- **D5 — Public API and read-model contract:** accepted
- **D6 — Runtime-free Workspace entry UX:** accepted

## Decisions

### runtime-260803/ADR-D1 — Agent owns Runtime capability; physical state remains in AgentRuntime

**Decision**

The Agent is the product source of truth for whether managed Runtime capability is
absent, enabled, or being removed. A durable Runtime-removal operation owns the
cross-system progress required to interrupt work, delete Runtime-owned resources,
retry after infrastructure unavailability, and finalize the transition.

`AgentRuntime` remains the physical execution-environment authority. It owns Provider
and Runner state, Workspace metadata, desired generation, configuration evidence,
physical lifecycle progress, and deletion acknowledgement. It does not determine
whether the Agent product grants Runtime capability.

A Runtime-free Agent may exist without an `AgentRuntime` row. Session and subagent
execution resolve Runtime authority from the Agent product state and do not create a
logical Runtime merely to accept input or run model-only work.

**Rationale**

This preserves the existing ownership direction in which AgentSession and
AgentRuntime are independent Agent-owned domains. It keeps user intent available
without Provider or Runner availability, allows Runtime-free execution without a
synthetic physical aggregate, and gives every admission boundary one Agent-owned
capability authority while retaining the established generation-fenced physical
Runtime control plane.

**Affected Requirements**

- `runtime-260803/REQ-1`
- `runtime-260803/REQ-3`
- `runtime-260803/REQ-4`
- `runtime-260803/REQ-6`
- `runtime-260803/REQ-8`
- `runtime-260803/REQ-10`

### runtime-260803/ADR-D2 — Final removal confirmation is irreversible

**Decision**

The administrator's final destructive confirmation is the commit point for Runtime
removal. After confirmation, the removal operation cannot be cancelled or rolled
back, including while Provider connectivity is unavailable or physical deletion is
still pending.

The Agent remains fenced from new work and Runtime use, removal-owned capability
revocation remains effective, and the durable operation continues retrying until
authoritative physical deletion is confirmed. Operational controls may inspect and
retry the removal, but they cannot restore the previous Runtime or declare an
ambiguous outcome successful.

**Rationale**

Once a distributed deletion command may have been dispatched, lost, partially
applied, or retried, the system cannot safely prove that the old Workspace remains
complete. Making confirmation irreversible avoids a second authority for rollback,
prevents partially deleted resources from being re-exposed, and keeps the user
meaning of permanent removal consistent with the infrastructure failure model.

**Affected Requirements**

- `runtime-260803/REQ-7`
- `runtime-260803/REQ-8`
- `runtime-260803/REQ-9`

### runtime-260803/ADR-D3 — Reuse the logical Runtime identity with a new physical generation

**Decision**

After terminal deletion is authoritatively acknowledged, adding a Runtime back to
the same Agent reuses that Agent's existing logical AgentRuntime identity and starts
a new physical incarnation under a higher desired generation.

The rearm transition is permitted only from an exactly acknowledged terminal-delete
state. It creates new desired configuration evidence, new generation-bound Runner
credentials, and new Provider resources with an empty Workspace. It does not restore
the previous Workspace path, Projects, Git worktrees, processes, credential
exposure, or other Runtime-only capability state.

Historical configuration revisions, lifecycle observations, and deletion evidence
remain attached to the logical Runtime. Previous Runner credentials and late
Provider or Runner reports remain invalid through existing generation fencing.

**Rationale**

AgentRuntime already represents one logical execution-environment domain per Agent,
while desired generation provides the physical-incarnation fence. Reusing that
identity preserves immutable configuration and deletion evidence, avoids replacing
references throughout SessionAgentContext and Runtime operations, and does not
weaken isolation because physical resources must first be proven absent and every
new authority is generation-bound.

**Affected Requirements**

- `runtime-260803/REQ-5`
- `runtime-260803/REQ-6`
- `runtime-260803/REQ-8`
- `runtime-260803/REQ-9`

### runtime-260803/ADR-D4 — Use one server-owned capability catalog and resolver

**Decision**

Azents uses one server-owned capability catalog and resolver as the authority for
whether a product feature requires a managed Runtime and whether the current Agent
may use it. Model-visible tools, Toolkit prompt and credential projections, Skills,
Workspace and Project operations, Git worktrees, Agent settings, and other
Runtime-dependent surfaces declare their required product capabilities and consume
the same resolved Agent capability result.

The server applies the result both when projecting an available surface and again
at the authoritative execution or mutation boundary. Public UI projections explain
the server result but do not maintain an independent hard-coded permission list.

Mixed Toolkits retain capability-granular behavior. For example, remote GitHub
tools can remain available without a Runtime while GitHub CLI credential injection
requires the relevant Runtime credential-exposure capability. Runtime-free
execution does not render prompts that claim unavailable shell or filesystem
capabilities.

**Rationale**

The current shell flag does not cover Workspace, Projects, Skills, mixed Toolkits,
or credential injection, and per-surface checks can drift from user guidance or
miss stale and indirect execution paths. A common resolver keeps UX explanation and
security enforcement aligned, supports partial Toolkit availability, and creates a
reviewable admission requirement for future Runtime-dependent features.

**Affected Requirements**

- `runtime-260803/REQ-2`
- `runtime-260803/REQ-3`
- `runtime-260803/REQ-4`
- `runtime-260803/REQ-6`
- `runtime-260803/REQ-8`
- `runtime-260803/REQ-9`

### runtime-260803/ADR-D5 — Use a unified Runtime read model and dedicated transition actions

**Decision**

The public Runtime management contract represents Runtime-free, managed, and
removing Agents as normal server-authoritative states. A Runtime-free Agent does not
produce a missing-resource error merely because no physical AgentRuntime row
exists.

The detailed read model combines Agent-owned Runtime capability, an optional durable
removal operation, and optional physical AgentRuntime state. It supplies
server-computed action availability for add, remove, start, stop, restart, reset,
and observation as applicable. Agent summary responses expose a compact capability
projection for list, creation, and settings surfaces.

Adding and permanently removing Runtime capability use dedicated transition actions
rather than the generic Agent patch contract. Existing physical lifecycle actions
remain available only while the unified state authorizes them. Endpoint names,
wire enum identifiers, and equivalent local response decomposition remain Design
details.

**Rationale**

Runtime absence is a valid product state rather than a missing physical resource.
Dedicated actions give explicit authority, idempotency, destructive confirmation,
and asynchronous operation semantics to addition and removal without overloading a
nullable Runtime Profile patch. A unified read model prevents clients from
reconstructing product state and action availability from raw Agent, Provider,
Runner, and removal records.

**Affected Requirements**

- `runtime-260803/REQ-1`
- `runtime-260803/REQ-2`
- `runtime-260803/REQ-4`
- `runtime-260803/REQ-5`
- `runtime-260803/REQ-7`
- `runtime-260803/REQ-8`
- `runtime-260803/REQ-9`

### runtime-260803/ADR-D6 — Keep the Workspace entry and show a capability-aware empty state

**Decision**

The Agent Workspace entry remains discoverable for Runtime-free Agents. Instead of
rendering a missing, stopped, or failed Runtime, the Workspace surface presents a
server-driven empty state that explains the Agent's available non-Runtime
capabilities and the additional shell, filesystem, persistent Workspace, Project,
Git, build, and test capabilities provided by a managed Runtime.

An authorized Agent administrator receives the contextual Add Runtime action. Other
members receive the same capability explanation without a control they are not
authorized to use. While removal is pending, the Workspace entry remains available
as the durable progress surface, reports that Workspace access is revoked, and does
not expose cancellation or re-addition.

**Rationale**

Keeping the entry preserves discovery at the moment a user looks for Workspace
functionality, reinforces the creation-time explanation, distinguishes an
intentional Runtime-free Agent from a stopped or failed Runtime, and provides one
stable place to observe irreversible removal progress. Hiding the entry would make
the missing capability and its management path difficult to discover.

**Affected Requirements**

- `runtime-260803/REQ-1`
- `runtime-260803/REQ-2`
- `runtime-260803/REQ-4`
- `runtime-260803/REQ-7`
- `runtime-260803/REQ-8`

## Fixed and Derived Outcomes

- Runtime capability is Agent-scoped and cannot be independently changed by a Session or subagent.
- New Agents default to no Runtime; existing Agents remain Runtime-capable after migration.
- Runtime Profile absence cannot be the sole Runtime-capability authority because an existing Runtime-capable Agent may have no selected Profile.
- Adding Runtime capability requires explicit administrator confirmation and an available Runtime Profile, but active compute remains lazily provisioned.
- Permanent removal immediately fences new Agent work, interrupts active work, deletes Runtime-owned Workspace state, and remains pending until deletion is authoritatively confirmed.
- Stop preserves Runtime capability and Workspace data.
- Runtime-only capabilities and credential exposure disabled by removal do not reactivate automatically after re-addition.

## Agent-Owned Implementation Details

The implementation may choose local identifiers, helper boundaries, file layout, repository method decomposition, internal event names, fixture composition, equivalent UI spacing and icon choices, and test-file organization as long as those choices introduce no new product behavior, state authority, lifecycle mode, interface contract, security boundary, or fallback.

## Consequences

- Agent reads and execution admission can determine Runtime authority without
  ensuring or resolving an AgentRuntime.
- Runtime removal requires a durable product operation distinct from the physical
  AgentRuntime lifecycle record.
- Public read models must combine Agent-owned capability state with optional
  AgentRuntime physical state without treating a missing row as `NOT_STARTED`.
- Removal confirmation requires sufficiently explicit impact presentation because
  no later cancellation boundary exists.
- Provider unavailability extends the pending removal duration but never restores
  Runtime capability or the old Workspace.
- AgentRuntime must support an explicit generation-advancing rearm transition only
  after exact terminal-deletion acknowledgement.
- Runtime identity remains stable for audit and references, while Workspace and
  Runner authority are incarnation-scoped and start fresh after re-addition.
- Runtime-required feature declarations and Agent capability resolution become a
  shared server contract used by both projection and authoritative admission.
- UI capability guidance is projected from server-owned semantics rather than
  acting as a second permission authority.
- Runtime-free and removing Agents remain readable through the Runtime management
  API even when no usable physical Runtime exists.
- Runtime capability transitions have dedicated command boundaries and are not
  encoded as nullable Runtime Profile updates.
- Workspace navigation remains stable across Runtime capability transitions and
  renders explicit Runtime-free or removal-progress states rather than hiding the
  surface or presenting a runtime failure.

## Rejected Options

### AgentRuntime owns both product capability and physical state

Rejected for D1. Requiring a logical AgentRuntime row for every Runtime-free Agent
would preserve the current input-admission coupling, mix user intent with
Provider/Runner lifecycle, and make a missing Profile, an absent capability, and an
unprovisioned execution environment compete inside one aggregate.

### Runtime capability is inferred from Runtime Profile selection

Rejected as inconsistent with confirmed compatibility requirements. An existing
Runtime-capable Agent may legitimately have no selected Profile, while a newly
created Runtime-free Agent also has no selected Profile.

### Cancellation before a Provider deletion dispatch

Rejected for D2. A dispatch result can be lost or become ambiguous across Control,
Provider, and backend failure boundaries. Restoring Agent capability on that basis
would require rollback authority and could re-expose a partially deleted Workspace
or previously revoked Runtime credentials.

### Retire the prior AgentRuntime and create a new logical identity

Rejected for D3. This would require multiple historical Runtime rows per Agent or
destructive removal of immutable configuration evidence, change every current
Runtime lookup into an active-incarnation selection, and relink dependent
SessionAgentContext and operation state without adding a stronger security boundary
than the existing desired-generation fence.

### Use only a coarse `has Runtime` gate

Rejected for D4. A single boolean does not describe mixed Toolkit behavior,
Runtime credential exposure, filesystem versus remote Skills, or future
Profile-specific availability, and it would leave user guidance maintained
separately from effective feature authority.

### Let each Runtime-dependent surface enforce its own rule

Rejected for D4. Independent Tool, Toolkit, Workspace, Project, Skill, and UI checks
would create multiple authorities that can drift and would not reliably reject
stale or indirect operations.

### Change Runtime capability through the generic Agent patch contract

Rejected for D5. A general partial update cannot cleanly express irreversible
destructive confirmation, durable removal progress, transition idempotency, and
server-owned action availability, and would overload Runtime Profile nullability
with incompatible meanings.

### Return a missing-resource error for Runtime-free Agents

Rejected for D5. Runtime absence is an intentional Agent state that must support
guidance and explicit addition; treating it as a missing resource would force
clients to reconstruct the product state from separate Agent data.

### Hide the Workspace entry when an Agent has no Runtime

Rejected for D6. Hiding the entry would reduce capability and management
discoverability, obscure whether the absence is intentional or permission-related,
and leave no stable contextual surface for observing Runtime removal progress.
