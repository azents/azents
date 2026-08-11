---
title: "Optional Managed Runtime Phase 1 Persistence Foundation"
created: 2026-08-10
tags: [agent, runtime, session, migration, backend]
---
# Phase Execution Plan

- Phase: `1 — Persistence foundation`
- Branch/base: `azents/runtime-optional-capability-1-foundation` → `main`
- PR boundary: Additive Agent capability, Runtime removal operation, Session binding
  persistence, migration backfills, and repository/domain primitives without
  activating Runtime-free or removal behavior.
- Inputs: Confirmed `runtime-260803/REQ`, accepted `runtime-260803/ADR-D1` through
  `ADR-D6`, approved `runtime-260803/DESIGN` revision 3.
- Deliverables:
  - Agent Runtime capability enum and optimistic version.
  - Durable Runtime removal operation schema and content-free progress data.
  - Session working-folder binding state and invalidation evidence with nullable
    historical path.
  - Terminal-delete acknowledgement kind persistence.
  - Existing Agents backfilled to `managed` and existing root contexts to `bound`
    without changing physical Runtime, Profile, folder bytes, cleanup status,
    product mode, ownership, or pin state.
  - Repository/domain primitives needed by later behavior phases.
- Non-goals: Runtime-free creation or execution, capability filtering, public
  add/remove endpoints, removal coordinator execution, Web changes, rollout
  enablement, and Living Spec promotion.
- Interfaces: PostgreSQL enums and rows, Agent and Session context domain
  projections, repository create/read/update/CAS methods, and existing AgentRuntime
  terminal-delete fields.
- Approved Design mechanisms: `M1`, `M2`, `M11`, `M13`.
- Authority references: `runtime-260803/REQ-1`, `REQ-3`, `REQ-6`, `REQ-8`,
  `REQ-9`, `REQ-10`; `runtime-260803/ADR-D1`, `ADR-D2`, `ADR-D3`;
  approved Design revision 3.
- Design delta: `None`
- Removal obligations: Replace schema-level mandatory non-null Session folder
  storage with an explicit binding lifecycle. Do not remove current behavioral path
  authority until Phase 3.
- Absence verification: Migration inspection and tests prove no required
  `working_folder_path` constraint remains, every legacy row receives an explicit
  binding state, and no migration creates a Runtime or dispatches lifecycle work.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Core contracts | root | `python/apps/azents/src/azents/core/enums.py`, repository data models | Approved state model | Typed capability, binding, operation, and acknowledgement contracts | Unit/model tests, Ruff, ty |
| RDB models | root | `python/apps/azents/src/azents/rdb/models/agent.py`, `agent_runtime.py`, `session_agent_context.py`, new removal model | Core contracts | Additive columns, enums, constraints, indexes | Metadata/schema tests |
| Repositories | root | `python/apps/azents/src/azents/repos/agent/`, `agent_runtime/`, `agent_session/`, new removal repository | RDB models | Locked reads, CAS transitions, operation persistence, binding primitives | Repository tests |
| Migration | root | `python/apps/azents/db-schemas/rdb/` | Models and backfill invariants | Generated linear Alembic revision and revision pointer | Upgrade/downgrade and migration tests |
| Snapshot baseline | root | `docs/azents/{requirements,adr,design}/runtime-260803-*`, Phase 1 and implementation plans | Approved documents | Tracked implementation authority | Snapshot validator |

- Integration order: Core enums/data → RDB models → generated Alembic revision →
  repositories → migration/repository tests → quality checks.
- Independent review: `hardtack` reviews Phase 1 against the approved state model,
  migration preservation requirements, PostgreSQL authority, enum/constraint
  correctness, and the absence of activated product behavior.
- Final validation: Snapshot validation; affected migration tests; Agent,
  AgentRuntime, SessionAgentContext, and removal repository tests; `uv run ruff
  check .`; `uv run ruff format --check .`; `uv run ty check --error-on-warning`
  for `python/apps/azents`.
- Scope-drift check: Phase 1 must remain additive. It must not change creation
  defaults, input admission, Runtime lifecycle dispatch, public API behavior, or
  frontend state. Every persisted mechanism maps to M1, M2, M11, or M13.
- Context checkpoint: Phase 1 establishes durable state and CAS primitives only.
  Phase 2 owns Runtime-free behavior, Phase 3 owns resource-path authority, Phase 4
  owns add/rearm and Control semantics, and Phase 5 owns coordinator execution.
