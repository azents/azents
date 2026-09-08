---
title: "Agent-Scoped Toolkit Management Phase 2 Backend Plan"
created: 2026-09-07
updated: 2026-09-07
tags: [toolkit, agent, api, oauth, backend, plan]
---

# Agent-Scoped Toolkit Management Phase 2 Backend Plan

## Phase Execution Plan

- Phase: `2/4 Backend capability`
- Branch/base: `toolkit-agent-scope-2-backend` → `toolkit-agent-scope-1-foundation`
- PR boundary: Expose the approved Agent-owned management/setup/OAuth capability and
  generated contracts on top of the isolated Phase 1 foundation.
- Inputs: Phase 1 PR #1711; confirmed `toolkit-260907/REQ`; accepted
  `toolkit-260907/ADR-D1` through `ADR-D4`; approved `toolkit-260907/DESIGN` revision
  `1`; Phase 1 owner/effective/locking interfaces.
- Deliverables: Owner/explicit-AgentAdmin authorization, redacted management projection,
  Agent-owned CRUD and connection tests, Agent-nested GitHub setup and MCP OAuth,
  owner/Workspace consistency, lifecycle cleanup evidence, Public OpenAPI, generated
  Python/TypeScript clients, and backend/API tests.
- Non-goals: Agent settings UI, tRPC product integration, callback presentation changes,
  browser E2E, Living Spec promotion, implementation marking, and plan cleanup.
- Interfaces: Agent-owned routes require active path Agent plus current Owner or explicit
  AgentAdmin; item mismatches and unauthorized item access share a 404 boundary; owner is
  immutable; owner create/update participate in Phase 1 locking; Workspace routes remain
  shared-only; signed OAuth state binds Workspace, Agent, Toolkit, User, redirect URI,
  verifier, and callback target.
- Approved Design mechanisms: `M1, M3, M4, M5, M7`
- Authority references: `toolkit-260907/REQ-1` through `REQ-9`;
  `toolkit-260907/ADR-D1`, `ADR-D3`, `ADR-D4`; current Toolkit, MCP OAuth, Agent, and
  Team Session Specs; Phase 1 effective and lock contracts; project generated-client and
  layered-architecture constraints.
- Design delta: `None`
- Removal obligations: replace Workspace-only OAuth state/callback assumptions for
  Agent-owned resources; replace ownership-sensitive direct route repository access with
  services; ensure no AgentToolkit projection is created; prove Workspace/shared routes
  cannot expose Agent-owned IDs.
- Absence verification: search Agent-owned create paths for ToolkitScope/AgentToolkit
  writes; search affected routes for direct Toolkit repository access; cross-route API
  tests prove non-disclosure; generated schema contains distinct Agent-nested operations.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Authority and domain service | root Agent | Toolkit service/data, AgentAdmin/Agent repository reuse | Phase 1 owner/locks | Active-Agent Owner/AgentAdmin context, management projection, CRUD | Service integration tests and authority matrix |
| Agent-owned persistence mutations | root Agent | Toolkit repository/service tests | Authority and Phase 1 locks | Create/update/enable/delete with owner consistency and effective slug checks | Repository/service/concurrency tests |
| Public Agent-nested API | root Agent | Toolkit Public API modules and data schemas | Service contracts | Collection/item/test/GitHub/OAuth routes with 403/404/409/422 mapping | API tests and OpenAPI dump |
| OAuth/setup services | root Agent | OAuth core, Toolkit setup/OAuth service modules, MCP connection tests | Authorized owner context | Typed Agent OAuth state, current User/authority checks, Agent callback context | State, revocation, token-storage, disconnect tests |
| Agent response capability | root Agent | Agent service/Public API response and tests | Existing can-manage derivation | Requester-relative Agent Toolkit management availability without Toolkit disclosure | Agent API tests |
| Generated clients | root Agent | Public OpenAPI and generated Python/TypeScript client outputs | Stable routes/schemas | New source-generated operations and types | Generator, Python import, TypeScript typecheck |
| Lifecycle and isolation evidence | root Agent | Agent decommission tests, Toolkit API tests | CRUD/OAuth | Agent delete removes owned config/credentials/OAuth; Workspace APIs hide owner rows | DB/service tests |
| Required public E2E | root Agent | Existing Toolkit public E2E and minimal deterministic support | Generated Python client | Owner/Admin CRUD, manager denial, cross-Agent isolation, runtime availability where bounded | Required public E2E or explicit Phase 3 assignment |
| Independent review | `toolkit-260907-reviewer` | Read-only | Stable Phase 2 diff | Security/authority/OAuth/API/locking/generated-contract review | Severity-ordered findings and drift result |

- Integration order: phase plan → authority context → Agent-owned repository/service
  mutations → management projection → provider test/GitHub setup → typed OAuth state and
  routes → Agent capability flag → API schemas/routes → OpenAPI and clients → lifecycle
  and authority tests → required public E2E where available → quality gates → independent
  review → corrections → final validation.
- Independent review: `toolkit-260907-reviewer` reviews the stable diff read-only against
  Requirements, ADR, Design revision `1`, Phase 1 contracts, this phase plan, authority
  non-disclosure, OAuth state and reauthorization, credential secrecy, lock ordering,
  generated API compatibility, no AgentToolkit projection, and removal absence.
- Final validation: affected backend pytest; migration/repository/service/API/OAuth/
  decommission tests; required public Toolkit E2E where included; Ruff format/check;
  configured Python `ty`; Public OpenAPI dump; generated Python and TypeScript clients;
  TypeScript typecheck for generated consumers; changed-file pre-commit; docs validation;
  `git diff --check`.
- Scope-drift check: M1/M3/M4/M5/M7 coverage is required; no Web product flow, new
  provider, draft, Chat behavior, automatic attachment, ownership conversion,
  AgentToolkit projection, feature flag, Session/user mode, or new readiness persistence
  may enter this phase.
- Context checkpoint: before PR creation record exact route/schema names, authorization
  behavior, owner mutation and OAuth evidence, generated outputs, lifecycle cascade,
  removal searches, review/corrections, remaining Phase 3 scope, risks, and
  `Design delta: None`.

## Phase Checkpoint

- Completed routes and schemas:
  - Agent management collection and Agent-owned create/read/update/delete under
    `/toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs`;
  - saved and unsaved Agent connection tests;
  - Agent-nested GitHub Platform install, OAuth, and installation-list operations;
  - Agent-nested MCP OAuth connect, exchange, and disconnect operations;
  - `AgentToolkitManagementResponse`, Agent-owned create/update request contracts, and
    requester-relative `toolkit_management_available` Agent response capability.
- Authorization behavior: active path Agent plus Workspace Owner or explicit AgentAdmin;
  Agent-level missing/cross-Workspace requests return 404 and authority denial returns
  403; Agent-owned item missing, cross-Agent, cross-Workspace, and authority denial use
  one nondisclosing 404 boundary.
- Ownership and mutation evidence: Agent-owned create writes canonical
  `owner_agent_id`, creates neither ToolkitScope nor AgentToolkit, locks the Agent row,
  and validates the effective slug namespace. Update/delete keep ownership immutable and
  revalidate exact owner/Workspace context under the required ToolkitConfig-then-Agent
  lock order.
- OAuth and setup evidence: Agent MCP state binds Workspace, Agent, Toolkit, User,
  redirect URI, PKCE verifier, and callback target. Agent GitHub state separately binds
  effective Platform generation, Workspace, Agent, initiating User, redirect URI, and
  callback target. Token/installation persistence and disconnect pass through
  authorization-aware ToolkitService methods that revalidate current authority and
  ownership. Cross-user GitHub state replay is rejected before exchange or sync.
- Generated contracts: Public OpenAPI, generated Python client, and ignored generated
  TypeScript public-client output contain the Agent-nested operations, Agent-local slug
  descriptions, management projection models, and Agent capability field. Python client
  compile/import and TypeScript public-client format, lint, and typecheck pass.
- Lifecycle and isolation evidence: deleting an Agent cascades its Agent-owned
  ToolkitConfig and dependent MCP OAuth row; Public Toolkit responses omit
  `owner_agent_id` and credentials while exposing only `has_credentials`; Workspace and
  shared attachment routes retain shared-only lookups.
- Removal and absence evidence: Agent-owned create contains no ToolkitScope or
  AgentToolkit write; Agent-nested GitHub and MCP OAuth route handlers no longer invoke
  their persistence repositories directly; no ownership conversion, automatic attach,
  new provider, draft, Chat, Session/user mode, or readiness persistence was added.
- Validation: 81 targeted backend tests passed, including migration, repository,
  service, API, OAuth, redaction, authority, and lifecycle coverage. Backend Ruff and
  full `ty` passed; OpenAPI generation and contract assertions passed; generated Python
  client compile/import passed; TypeScript public-client format/lint/typecheck passed;
  `git diff --check` passed.
- Independent review: initial review found one high and two medium implementation
  drifts. Typed Agent GitHub state, authorization-aware setup persistence, and distinct
  Agent-local slug contracts corrected them. Targeted re-review found no blocking, high,
  or medium findings and independently passed 57 focused tests.
- Remaining Phase 3 scope: saved Agent settings UI, tRPC integration, callback
  presentation and fallback navigation, Storybook, browser E2E, localization, and Living
  Spec promotion.
- Residual risk: AgentAdmin revocation can race in a narrow interval after a transaction's
  current-authority check; persisted operations still revalidate authority immediately
  before their write boundary and no reviewer-classified blocking/high/medium issue
  remains.
- Design delta: `None`.
