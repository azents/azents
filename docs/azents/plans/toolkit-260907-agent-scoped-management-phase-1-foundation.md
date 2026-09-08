---
title: "Agent-Scoped Toolkit Management Phase 1 Foundation Plan"
created: 2026-09-07
updated: 2026-09-07
tags: [toolkit, database, backend, engine, plan]
---

# Agent-Scoped Toolkit Management Phase 1 Foundation Plan

## Phase Execution Plan

- Phase: `1/4 Foundation`
- Branch/base: `toolkit-agent-scope-1-foundation` → `main`
- PR boundary: Add the persistence and compatibility foundation without exposing an
  Agent-owned management write surface.
- Inputs: confirmed `toolkit-260907/REQ`, accepted `toolkit-260907/ADR-D1` through
  `ADR-D4`, approved `toolkit-260907/DESIGN` revision `1`.
- Deliverables: nullable canonical owner, partial local slug indexes, shared-only
  Workspace boundaries, canonical effective Toolkit relation, serialized namespace
  mutations, Runtime/VFS/Platform GitHub App consumer cutover, and focused tests.
- Non-goals: Agent-nested management/setup/OAuth routes, generated API changes, Web UI,
  browser E2E, Living Spec promotion, and implementation marking.
- Interfaces: `owner_agent_id` is canonical; `AgentToolkit` remains shared-only; effective
  reads return shared-attachment or Agent-owned source; shared routes expose only null
  owners; lock order is ToolkitConfig then ascending Agent IDs.
- Approved Design mechanisms: `M1, M2, M3, M8`
- Authority references: `toolkit-260907/REQ-3`, `REQ-4`, `REQ-7`, `REQ-8`, `REQ-9`;
  `toolkit-260907/ADR-D1`, `ADR-D2`, `ADR-D3`, `ADR-D4`; current Toolkit, MCP OAuth,
  Agent execution, and VFS Specs; project migration and layered-architecture constraints.
- Design delta: `None`
- Removal obligations: replace Workspace-wide slug constraint; make Workspace/shared
  repository and provider-setup reads shared-only; replace AgentToolkit-only
  Runtime/VFS eligibility and Platform GitHub App impact count; establish safe rollback
  foundation.
- Absence verification: search for old unique constraint authority, direct effective
  `AgentToolkitRepository.list_by_agent()` consumers, unfiltered same-Workspace Toolkit
  item reads, and attachment-only impact aggregation; targeted tests prove replacements.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Schema and migration | root Agent | Toolkit RDB model, Alembic revision, schema revision file | Approved M1/M8 | Owner FK/indexes, partial unique indexes, downgrade precondition | Migration/schema tests, Alembic checks |
| Repository contracts | root Agent | `repos/toolkit/**` | Schema | Owner-aware domain models, shared-only operations, effective relation, lock helpers | Repository tests, constraint mapping tests |
| Shared service hardening | root Agent | `services/toolkit/**`, existing Toolkit routes only as needed | Repository | Shared create/list/get/update/delete/scope/test/OAuth lookups cannot reach Agent-owned rows | Service/API regression tests |
| Runtime/VFS cutover | root Agent | `engine/run/resolve.py`, `services/vfs.py`, worker/deps and tests | Effective relation | Both consumers resolve shared attachments plus direct owners and reject duplicate slugs | Resolve/VFS tests and focused type checks |
| GitHub impact cutover | root Agent | Platform GitHub App repository/service tests | Effective relation | Affected Agent count includes shared attachments and direct owners | Aggregate tests |
| Namespace serialization | root Agent | Toolkit repository/service transaction paths and tests | Owner/effective relation | Shared attach/update/enable and owner-capable helpers use deterministic locks and conflict errors | Concurrent integration tests |
| Documentation baseline | root Agent | snapshot docs, implementation plan, phase plan, generated docs index | Approved Design | Approval recorded and tracked execution context | Snapshot validator, docs index, diff check |
| Independent review | `toolkit-260907-reviewer` | Read-only | Stable phase diff | Review for authority, migration safety, isolation, concurrency, removal, test adequacy | Written findings with severity and file references |

- Integration order: approval/docs baseline → schema migration → repository/domain
  contracts → effective relation and lock helpers → shared service filtering →
  Runtime/VFS/impact cutover → focused tests → documentation validation → independent
  review → required corrections → final validation.
- Independent review: `toolkit-260907-reviewer` reviews the stable branch read-only
  against Requirements, ADR, Design revision `1`, this phase contract, database rollback
  safety, cross-tenant/owner isolation, lock ordering and race coverage, Runtime/VFS
  completeness, and removal absence. Output is a bounded findings report; only security,
  data-loss, requirement/design, material convention/interface issues require re-review.
- Final validation: targeted Toolkit repository/service/API pytest; runtime resolve and
  VFS pytest; Platform GitHub App service pytest; migration tests; Ruff format/check;
  configured `ty`; docs pre-commit hook; snapshot validator; `git diff --check`.
- Scope-drift check: M1/M2/M3/M8 coverage is required; no Agent-nested write API, UI,
  new ownership representation, feature flag, conversion, provider type, draft, Chat,
  Session/user scope, or compatibility fallback may enter this phase.
- Context checkpoint: before PR creation record schema and query interfaces, old-path
  absence evidence, exact test commands/results, review findings/corrections, remaining
  Phase 2 work, relevant paths, rollout risk, and `Design delta: None`.

## Phase 1 Context Checkpoint

- Completed behavior: added nullable Agent ownership with cascade and partial local slug
  indexes; made Workspace and attachment reads shared-only; centralized enabled effective
  Toolkit resolution; serialized shared attach/update namespace changes; moved Runtime,
  VFS, and Platform GitHub App impact to the effective relation.
- Changed interfaces: `ToolkitConfig` and `ToolkitCreate` carry required nullable
  `owner_agent_id`; `ToolkitRepository.list_effective_for_agent()` returns typed source
  projections; `resolve_agent_tools()` and `VfsProjectionService` no longer depend on an
  AgentToolkit repository as the complete effective source.
- Removal evidence: production search leaves AgentToolkit repository use only in the
  shared attachment service; Workspace Toolkit service and OAuth item reads use
  shared-only repository operations; GitHub impact aggregation uses the canonical
  relation; the old Workspace-wide unique constraint exists only in migration downgrade
  and historical documentation.
- Validation evidence: Ruff format/check passed; full configured Python `ty` passed;
  migration round-trip/downgrade test passed; the final stable phase matrix passed with
  132 tests, including the concurrent attach/update race and Runtime/VFS defensive
  duplicate-slug failures.
- Independent review: `toolkit-260907-reviewer` reported no blocking, high, or medium
  findings and confirmed `Design delta: None`. Follow-up consumer-level duplicate-slug
  fail-closed tests were added for Runtime and VFS. Credential/OAuth dependent-row
  cascade evidence remains assigned to Phase 2/3.
- Remaining scope: Agent authority and owner CRUD, setup/OAuth routes, generated clients,
  Agent settings UI, callback routing, E2E, Living Specs, implementation marking, and
  plan cleanup.
- Residual risks: owner/Workspace consistency must be enforced by the Phase 2
  authoritative create/update transaction; shared Toolkit updates lock every attached
  Agent and require later scale observation; rollback must not go earlier than this
  foundation after Agent-owned rows exist.
- Design delta: `None`.
