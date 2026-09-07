---
title: "Agent-Scoped Toolkit Management Decisions"
created: 2026-09-07
tags: [toolkit, agent, api, security, architecture]
document_role: primary
document_type: adr
snapshot_id: toolkit-260907
---

# toolkit-260907/ADR: Agent-Scoped Toolkit Management Decisions

- Snapshot: `toolkit-260907`
- Document reference: `toolkit-260907/ADR`
- Requirements:
  [`toolkit-260907/REQ`](../requirements/toolkit-260907-agent-scoped-management.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

Persisted Toolkit configuration currently has one ownership and visibility model:
`ToolkitConfig.workspace_id` owns the object, creation automatically adds a Workspace
`ToolkitScope`, Workspace Managers manage the object through `TOOLKITS_WRITE`, and
`AgentToolkit` attaches the configuration to an Agent for runtime resolution.

The confirmed Requirements add a second product ownership boundary. An Agent-only
Toolkit must be managed only by an explicit administrator of that Agent or a Workspace
Owner, remain undiscoverable to other Agents and non-administrators, and still use the
normal persisted Toolkit runtime, credential, OAuth, and provider behavior.

The current runtime contains no Human execution identity. Runtime authorization must
therefore continue to be resolved completely at management time and through canonical
Workspace, Agent, Toolkit, and attachment state rather than by carrying the configuring
User into a Run.

## Current-System Evidence

- `toolkit_configs` has a required `workspace_id` and Workspace-wide unique slug but no
  Agent owner.
- `toolkit_scopes` supports only `scope_type=workspace`; `scope_id` has no typed foreign
  key to an owning resource.
- `agent_toolkits` is the current persisted Agent-to-Toolkit runtime binding.
- Runtime and managed Toolkit VFS eligibility begin from Agent Toolkit bindings and then
  load the referenced ToolkitConfig.
- Workspace Toolkit CRUD, connection testing, GitHub installation discovery, and MCP
  OAuth routes require `TOOLKITS_WRITE`, which Workspace Managers possess.
- Other Agent settings services already derive management authority as Workspace Owner
  or explicit `AgentAdmin`.
- Existing Workspace Toolkit attachment routes use `TOOLKITS_READ` and are part of the
  compatibility boundary for current non-administrator behavior.
- ToolkitConfig deletion cascades current ToolkitScope, AgentToolkit, and MCP OAuth
  connection rows.

## Fixed and Derived Outcomes

- Existing ToolkitConfig rows remain Workspace-shared after migration.
- Workspace Toolkit management and existing shared attach/detach authorization remain
  unchanged.
- Agent-only management requires current Workspace Owner or explicit AgentAdmin
  authority at every management and OAuth boundary.
- Agent-only configuration retains the owning Workspace for isolation, provider setup,
  and runtime context.
- Agent-only credentials use the existing encrypted Toolkit credential storage and are
  never returned to clients.
- Agent deletion must remove its Agent-only Toolkit configuration and credentials;
  Workspace deletion continues to remove every Toolkit in the Workspace.
- No Agent-only Toolkit management authority or configuring User identity is carried
  into runtime execution.
- No draft resource, legacy fallback, automatic shared attachment, or conversion
  between Agent-only and Workspace-shared ownership is introduced.

## Material Decision Map

- [x] `toolkit-260907/ADR-D1` — canonical persisted ownership model for an Agent-only
  ToolkitConfig: nullable owning-Agent foreign key
- [x] `toolkit-260907/ADR-D2` — effective runtime-binding representation for Agent-only
  Toolkits: direct owner-based resolution without a projection row
- [x] `toolkit-260907/ADR-D3` — slug uniqueness and model-visible namespace collision
  boundary: scope-local uniqueness with serialized effective checks
- [x] `toolkit-260907/ADR-D4` — Agent-scoped CRUD, setup, connection-test, and OAuth API
  boundary

## Decisions

### toolkit-260907/ADR-D1. Store Agent-only ownership on ToolkitConfig

**Affects:** `toolkit-260907/REQ-3`, `REQ-4`, `REQ-7`, `REQ-8`

ToolkitConfig receives a nullable owning-Agent foreign key. A null owner identifies an
existing Workspace-shared Toolkit; a non-null owner identifies an Agent-only Toolkit in
the same Workspace.

The owning Agent is the canonical authority for Agent-only visibility, management, and
lifecycle. ToolkitScope remains a visibility mechanism for Workspace-shared Toolkits,
and an execution attachment does not become an ownership source of truth.

**Consequences**

- Ownership is explicit on the resource that stores configuration and credentials.
- Existing ToolkitConfig rows migrate with a null owner and retain Workspace-shared
  semantics.
- Agent-only authorization and list queries do not infer ownership from ToolkitScope or
  AgentToolkit state.
- The owning-Agent foreign key uses cascading deletion so Agent deletion removes its
  Agent-only Toolkit configuration and credentials.
- Agent-only create and ownership-sensitive updates validate that the Agent and Toolkit
  belong to the same Workspace in the authoritative service transaction.
- Separate AgentToolkitConfig persistence and Agent ownership encoded as an untyped
  ToolkitScope are rejected.

### toolkit-260907/ADR-D2. Resolve Agent-owned Toolkits directly from ownership

**Affects:** `toolkit-260907/REQ-3`, `REQ-7`, `REQ-8`, `REQ-9`

AgentToolkit continues to represent only explicit Workspace-shared attachments.
Agent-owned Toolkit availability is derived directly from
`ToolkitConfig.owner_agent_id`; no AgentToolkit or second binding row is created for an
Agent-owned Toolkit.

Runtime, managed VFS, Toolkit impact reporting, and other effective-Toolkit consumers
use one repository operation that returns the union of:

1. enabled Workspace-shared ToolkitConfigs explicitly attached through AgentToolkit;
2. enabled ToolkitConfigs whose owning Agent is the current Agent.

**Consequences**

- Agent-owned configuration cannot become orphaned from a required projection or
  attachment row.
- The owning ToolkitConfig is both the ownership and Agent-only availability authority.
- Shared attachment list and detach APIs remain structurally unable to expose or remove
  Agent-owned Toolkits.
- Effective-Toolkit queries must centralize the two-source union so runtime, VFS, impact,
  and future consumers cannot implement different eligibility rules.
- Namespace integrity cannot depend on a complete AgentToolkit projection and is
  resolved separately in D3.
- Mandatory AgentToolkit projections and a separate Agent-only binding table are
  rejected because both create a second persisted lifecycle that can drift or become
  orphaned.

### toolkit-260907/ADR-D3. Use scope-local slugs with serialized effective checks

**Affects:** `toolkit-260907/REQ-3`, `REQ-5`, `REQ-8`, `REQ-9`

Workspace-shared slugs remain unique within the Workspace, while Agent-owned slugs are
unique within their owning Agent. The configured slug remains the actual model-visible
tool prefix for both ownership types.

Every authoritative operation that can introduce or change one Agent's effective slug
set serializes on Agent rows before checking the D2 union:

- shared Toolkit attachment locks the target Agent;
- Agent-owned create or slug update locks the owner Agent;
- shared Toolkit slug update locks all attached Agents in deterministic Agent-ID order.

The transaction rejects an operation when the resulting effective Toolkit set for any
locked Agent contains a duplicate slug. Runtime resolution defensively asserts unique
slugs and fails closed if storage was modified outside the authoritative service path.

**Consequences**

- Separate Agents can use the same natural Agent-owned slug without discovering each
  other.
- Existing Workspace-shared slug semantics and model-visible tool names remain.
- The schema uses partial unique constraints for Workspace-shared and Agent-owned local
  slug domains, with cross-source effective uniqueness owned by serialized service
  transactions.
- No namespace claim or projection row can become orphaned.
- Shared slug changes may be rejected when the new prefix conflicts in an attached
  Agent; the error does not identify the hidden conflicting Toolkit.
- All attachment and slug-mutation paths must participate in the Agent-row locking
  contract.
- A broader redesign of user-configured slugs and internal model namespaces is deferred
  to a later Requirements and design snapshot.

### toolkit-260907/ADR-D4. Agent-scoped API and OAuth boundary

**Affects:** `toolkit-260907/REQ-1` through `REQ-7`, `REQ-9`

Agent-only management and provider setup use explicit Agent-nested routes. The route
family covers management list, create, read, update, delete, unsaved and saved
connection tests, GitHub Platform App setup, and Toolkit OAuth connect, exchange, and
disconnect.

Every route resolves the Agent in the Workspace and derives current management
authority as Workspace Owner or explicit AgentAdmin. Item routes additionally require
the ToolkitConfig owner to equal the path Agent. Unauthorized and ownership-mismatched
requests use the same non-disclosing not-found boundary.

Existing Workspace Toolkit CRUD, available-list, shared attach, and shared detach routes
continue to accept only Workspace-shared ToolkitConfigs and keep their current
permission contracts. Provider-specific validation, credential storage, connection
testing, and OAuth protocol services remain reusable below the route authorization
boundary.

OAuth state and redirect context bind the exact Workspace, Agent, ToolkitConfig,
initiating User, and callback target. Exchange and disconnect revalidate current Agent
management authority instead of treating the signed start state as continuing
authorization. The Web callback returns to the owning Agent's Toolkit settings context.

**Consequences**

- Route shape makes the ownership and authorization boundary explicit.
- Workspace Managers cannot reach Agent-owned state through existing `TOOLKITS_WRITE`
  endpoints.
- Shared generated-client functions remain compatible; Agent-only functions are new
  additions.
- Provider validation and credential/OAuth service logic can be shared below the route
  authority layer.
- Frontend Agent settings use one Agent-management projection containing attached shared
  candidates and owned Toolkit details; existing non-administrator attachment responses
  do not gain Agent-owned data.

Extending Workspace routes with an optional Agent ownership mode is rejected because it
would make every existing endpoint role-polymorphic and increase the risk that Workspace
Manager authority crosses into Agent-owned state. A single setup command endpoint is
rejected because saved disconnect, retry, edit, disable, delete, and provider-specific
authorization still require durable resource APIs with explicit failure boundaries.
