---
title: "Agent-Scoped Toolkit Management Implementation Plan"
created: 2026-09-07
updated: 2026-09-07
tags: [toolkit, agent, backend, frontend, api, engine, testenv]
---

# Agent-Scoped Toolkit Management Implementation Plan

- Requirements:
  [`toolkit-260907/REQ`](../requirements/toolkit-260907-agent-scoped-management.md)
- ADR: [`toolkit-260907/ADR`](../adr/toolkit-260907-agent-scoped-management.md)
- Approved Design:
  [`toolkit-260907/DESIGN`](../design/toolkit-260907-agent-scoped-management.md),
  revision `1`
- Approved Design mechanisms: `M1, M2, M3, M4, M5, M6, M7, M8`
- Design delta: `None`
- Primary implementation owner: root Agent
- Exact independent reviewer: `toolkit-260907-reviewer`

## Delivery Shape

Use four stacked PRs because the approved M8 rollout boundary requires shared-reader
hardening before any Agent-owned write surface, while backend API and Web/E2E changes
remain independently reviewable.

| Phase | Branch | Base | Approved mechanisms | Reviewable outcome |
| --- | --- | --- | --- | --- |
| 1. Foundation | `toolkit-agent-scope-1-foundation` | `main` | M1, M2, M3, M8 | Schema, shared-only hardening, effective relation, namespace serialization, runtime/VFS/impact cutover |
| 2. Backend capability | `toolkit-agent-scope-2-backend` | phase 1 | M1, M3, M4, M5, M7 | Agent-nested CRUD/setup/OAuth APIs, authority, redacted management projection, generated clients |
| 3. Product and validation | `toolkit-agent-scope-3-product` | phase 2 | M5, M6, M7 | Saved Agent settings UX, callback routing, localization, E2E, Living Specs, implemented snapshot |
| 4. Plan cleanup | `toolkit-agent-scope-4-cleanup` | phase 3 | M8 | Remove temporary implementation plans after validated spec promotion |

Create every PR before monitoring CI. Do not merge any PR without explicit requester
approval for that merge.

## Phase Dependencies and Interfaces

### Phase 1 → Phase 2

Phase 1 fixes the persistence and read boundaries consumed by Phase 2:

- `ToolkitConfig.owner_agent_id` is nullable canonical ownership.
- shared repository/service operations require `owner_agent_id IS NULL`.
- AgentToolkit remains shared-only.
- canonical effective Toolkit operations return source kind plus ToolkitConfig data.
- lock helpers serialize ToolkitConfig/Agent mutations and map namespace conflicts.
- Runtime, VFS, and Platform GitHub App impact use the effective relation.

Phase 2 must not introduce another persisted ownership or binding source.

### Phase 2 → Phase 3

Phase 2 fixes generated Public API contracts consumed by Phase 3:

- requester-relative Agent Toolkit management availability;
- redacted ownership-discriminated management projection;
- Agent-owned create/read/update/delete and test-connection operations;
- Agent-nested GitHub Platform App setup operations;
- Agent-nested MCP OAuth connect/exchange/disconnect operations; and
- exact callback context fields.

Phase 3 uses generated clients only and does not hand-write API paths.

### Phase 3 → Phase 4

Phase 3 completes deterministic validation, Specs, and matching `implemented` dates on
Requirements and Design. Phase 4 then removes this plan and every phase plan without
changing behavior.

## Workstreams and Ownership

| Workstream | Owner | Paths | Integration boundary |
| --- | --- | --- | --- |
| Persistence and migration | root Agent | `python/apps/azents/src/azents/rdb/models/toolkit.py`, `python/apps/azents/db-schemas/rdb/**` | Nullable owner, partial indexes, cascade, downgrade guard |
| Repository/effective relation | root Agent | `python/apps/azents/src/azents/repos/toolkit/**`, GitHub impact repository | Shared/owned filters, typed effective source, aggregate semantics |
| Service/API/OAuth | root Agent | `python/apps/azents/src/azents/services/toolkit/**`, `python/apps/azents/src/azents/api/public/toolkit/v1/**`, `core/oauth2.py` | Owner/AgentAdmin authority and non-disclosing ownership routes |
| Runtime and VFS | root Agent | `engine/run/resolve.py`, `services/vfs.py`, worker/dependency wiring | Canonical effective Toolkit reads and fail-closed slug checks |
| Generated contracts | root Agent | Public OpenAPI and generated Python/TypeScript clients | Source-generated only |
| Web product flow | root Agent | azents-web Agent Toolkit feature, tRPC, callback, messages, stories | Container/component ADT and ownership-correct actions |
| E2E and fixtures | root Agent | `testenv/azents/e2e/**` and only required fixture support | Product APIs only; deterministic local providers; no direct DB writes |
| Specs and snapshot finalization | root Agent | Toolkit/Agent/execution/OAuth Specs and snapshot documents | Current behavior promotion after validation |
| Independent review | `toolkit-260907-reviewer` | Read-only review of each stable phase diff | Requirements, ADR, Design, phase contract, security and drift |

No implementation paths overlap with the reviewer because the reviewer does not edit.

## Removal Obligations

The phases own all Design removal items:

- Phase 1 replaces Workspace-wide slug uniqueness, same-Workspace-as-shared assumptions,
  AgentToolkit-only runtime/VFS reads, and attachment-only GitHub impact counts.
- Phase 2 replaces Workspace-only OAuth callback context and ownership-sensitive direct
  route repository access; it proves no AgentToolkit projection exists for Agent-owned
  Toolkits.
- Phase 3 replaces the query-coupled Agent Toolkit selector with the approved management
  flow while retaining the legacy non-admin path.
- Phase 1 establishes the foundation release as the minimum safe rollback target.
- Phase 4 removes plans only after all functional removals have absence evidence.

## Validation Matrix

### Phase 1

- Alembic migration upgrade/downgrade tests and current revision validation.
- Toolkit repository/service tests for shared filters, owner consistency, partial
  uniqueness, lock ordering, concurrent conflicts, effective relation, and impact count.
- Runtime resolve and VFS tests for shared plus Agent-owned candidates and defensive
  duplicate failure.
- Python Ruff, formatter check, `ty`, and targeted pytest.

### Phase 2

- Service/API tests for Owner, explicit AgentAdmin, Workspace Manager, Member,
  cross-Agent, cross-Workspace, active/decommissioning Agent, and credential redaction.
- OAuth state, initiating-User, authority-revocation, Agent callback, GitHub setup, and
  provider-test coverage.
- Public OpenAPI dump and generated Python/TypeScript client generation.
- Required public E2E for CRUD, isolation, runtime availability, disable/delete, and
  shared compatibility where deterministic fixtures permit.
- Python and TypeScript generated-contract quality checks.

### Phase 3

- azents-web component/container/tRPC/callback tests and Storybook state coverage.
- All locale structure tests, format, lint, typecheck, and build.
- Required public and browser E2E for the approved end-to-end matrix, keyboard use, and
  narrow layouts.
- Spec review, snapshot traceability, removal/absence audit, and matching implemented
  dates.

### Phase 4

- Documentation index/snapshot validation and `git diff --check` after plan removal.
- Full stack status and CI review after all four PRs exist.

## E2E Fixtures and Prerequisites

Use or add deterministic local MCP/OAuth behavior within the existing credential-free
E2E substrate. Create Workspace Owner, Workspace Manager, Member, explicit AgentAdmin,
Agents, shared Toolkits, and Agent-owned Toolkits through product APIs. E2E must not
write directly to the product database.

No live external credential is required. Optional live provider verification may run
only from a prepared prerequisite snapshot; configured live failures fail the requested
run and absent prerequisites may skip only that optional coverage.

## Spec Impact

Phase 3 updates at least:

- `docs/azents/spec/domain/toolkit.md`;
- `docs/azents/spec/domain/agent.md` when the settings/authority projection changes;
- `docs/azents/spec/flow/mcp-oauth.md`; and
- `docs/azents/spec/flow/agent-execution-loop.md` for effective persisted Toolkit
  resolution.

Run `/spec-review` before final snapshot implementation marking.

## Rollout, Rollback, and External Actions

- Roll out Phase 1 before Phase 2 can create any Agent-owned row.
- After Agent-owned rows exist, roll back only to the Phase 1 foundation or later.
- Schema downgrade must reject non-null owners and never delete or convert them.
- No Kubernetes, cloud, provider, database-manual-write, or live infrastructure action
  is authorized or required.
- PR merge remains requester-controlled.

## Scope and Context Checkpoints

At each phase boundary record:

- completed observable behavior and approved mechanism coverage;
- changed persistence/API/runtime/Web interfaces;
- validation and review evidence;
- completed removal obligations and absence searches;
- remaining phase scope;
- exact branch/base and relevant paths;
- non-blocking risks and blockers; and
- `Design delta: None` or an immediate return to technical design.

## Blockers

None at plan creation. The approved Design is feasible, revision `1` approval covers the
exact authority set `M1` through `M8`, and all material ADR decisions are accepted.
