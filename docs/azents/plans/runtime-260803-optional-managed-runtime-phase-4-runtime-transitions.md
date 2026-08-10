---
title: "Optional Managed Runtime Phase 4 Runtime Transitions"
created: 2026-08-10
tags: [agent, runtime, control, provider, backend, migration]
---
# Phase Execution Plan

- Phase: `4 — Runtime add, rearm, and Control transitions`
- Branch/base: `azents/runtime-optional-capability-4-runtime-transitions` →
  `azents/runtime-optional-capability-3-session-bindings`
- PR boundary: Add the internal explicit Runtime addition/rearm domain transition,
  exact Profile-source transaction fences, terminal acknowledgement authorities,
  and reconnect-safe terminal-delete dispatch needed before the removal coordinator
  and public management contracts are introduced.
- Inputs: Phase 3 commit `bd0113742`; confirmed `runtime-260803/REQ`;
  accepted `runtime-260803/ADR-D2`, `ADR-D3`, `ADR-D4`, and `ADR-D5`;
  approved `runtime-260803/DESIGN` revision 3; Phase 1 capability/removal
  persistence; Phase 2 managed-only lifecycle admission; Phase 3 exact Runtime and
  Session binding authority.
- Deliverables:
  - One internal explicit-add transition accepts an Agent in `none`, expected
    capability/Profile versions, one explicit available Workspace Runtime Profile,
    and one bounded idempotency identity. It commits capability `managed`, advances
    both optimistic versions, records a durable transition receipt, and leaves the
    logical Runtime configured in stopped state without dispatching Provider work.
  - A first add creates one stable logical `AgentRuntime` and attaches an immutable
    desired configuration revision from exact Workspace Profile, infrastructure
    Profile, Provider, capability-contract, and Agent-selection snapshots.
  - A re-add reuses only the Agent's exactly terminally acknowledged logical Runtime
    after the prior removal operation completed. It advances desired generation,
    clears incarnation-scoped Provider/Runner observation, Workspace, failure,
    applied-revision, credential/dispatch authority, and terminal request fields,
    then attaches a fresh desired revision for the explicit Profile.
  - Rearm never restores shell, Runtime credential projection, Projects, worktrees,
    Runtime-only settings, filesystem Skill state, or any historical Session
    working-folder binding. Existing invalidated/none contexts remain terminal.
  - Existing immutable Provider binding remains authoritative. A re-add Profile
    whose exact Provider conflicts with the retained logical Runtime fails closed;
    no Provider reassignment or compatibility fallback is introduced.
  - Terminal deletion supports two exact acknowledgement authorities:
    current-generation `provider_report` and a locked, narrowly proven
    `no_physical_binding` transition for a logical Runtime that has no Provider
    binding, dispatch-capable configuration, Workspace path, or physical
    observation.
  - Terminal-delete retry discovery does not trust persisted connection state as
    current route authority. The reconciler consults the coordination store and may
    redispatch only through the current Provider connection generation after
    reconnect or leader recovery.
- Non-goals: Removal confirmation/API, Agent-wide interruption, product cleanup,
  Session binding invalidation batches, physical-deletion orchestration ownership,
  public Runtime read models or routes, OpenAPI/generated clients, Web UX, E2E
  rollout, Living Spec promotion, automatic Runtime addition, Provider reassignment,
  or Runtime start during addition.
- Interfaces:
  - The add transition returns one immutable result containing the updated Agent,
    logical Runtime, exact desired configuration revision, committed capability and
    Profile-selection versions, desired generation, and whether the durable
    idempotency receipt was newly created or replayed.
  - A durable add receipt is unique by Agent and idempotency key and records the
    requested Profile, expected/committed capability version, committed
    Profile-selection version, logical Runtime ID, desired generation, and creation
    time. A replay succeeds only when all request identity and committed-result
    evidence match.
  - Profile resolution exposes one reusable exact-source preparation boundary;
    attachment remains guarded by Agent selection, Provider admin/capability,
    infrastructure Profile, Workspace Runtime Profile, desired revision, and desired
    generation compare-and-set evidence.
  - Rearm and `no_physical_binding` acknowledgement are repository-owned locked
    transitions. Callers cannot clear terminal evidence or claim absence by writing
    fields independently.
  - Runtime Control dispatch continues to use the existing Provider command
    protocol and exact desired generation. Coordination-store connection generation
    is dispatch authority; the persisted connection enum is observation/cache only.
- Approved Design mechanisms: `M3`, `M8`, `M9`, `M11`, `M15`.
- Authority references: `runtime-260803/REQ-4`, `REQ-5`, `REQ-8`, `REQ-9`;
  `runtime-260803/ADR-D2`, `ADR-D3`, `ADR-D4`, `ADR-D5`; approved Design revision
  3; current `agent-runtime-control` and `agent-runtime-persistence` Specs.
- Design delta: `None`
- Removal obligations:
  - Replace generic Profile mutation as a possible capability grant with a dedicated
    internal add transition boundary. Public route replacement remains Phase 6.
  - Replace terminal delete as a permanent logical dead end with exact-acknowledgement
    higher-generation rearm.
  - Replace Provider reconnect retry that depends on stale persisted connection
    cache with current coordination-route qualification.
  - Preserve immutable Provider binding and existing generation/report fences; do
    not add a second Runtime identity or Provider fallback.
- Absence verification:
  - Generic Agent patch has no `none → managed` path and cannot enable Runtime-only
    settings for Runtime-free/removing Agents.
  - Add/rearm tests prove zero Provider dispatch, zero Runner dispatch, stopped
    desired state, disabled shell, null Workspace path, and no historical Session
    binding mutation.
  - Repository searches find no direct terminal-field clearing or
    `no_physical_binding` acknowledgement outside the owning transition methods.
  - Reconnect tests prove a stale Provider connection generation cannot receive a
    terminal-delete command and a current generation can redispatch the same desired
    deletion generation.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Add receipt and transition persistence | `root` | `rdb/models/`, new Alembic revision, `repos/agent_runtime_add/`, `repos/agent/` | Phase 1 Agent capability fields | durable idempotency receipt, exact Agent capability/Profile CAS | migration, model, repository idempotency and concurrency tests |
| Exact Profile preparation and add/rearm service | `root` | `services/runtime_profile_resolution/`, new focused Runtime transition service, `repos/runtime_profile/` | add receipt, Agent/Runtime locks | explicit first-add and acknowledged-rearm transaction with stopped desired revision | source-race, stale-version, blocked-Profile, replay, no-start service tests |
| Logical Runtime terminal transitions | `root` | `repos/agent_runtime/`, `repos/agent_runtime_removal/` | Phase 1 terminal fields and removal evidence | exact completed-removal lookup, `no_physical_binding` acknowledgement, higher-generation rearm with incarnation cleanup | repository generation, stale-report, immutable-binding, observation-clearing tests |
| Reconnect-safe terminal delete Control | `root` | `runtime/control_protocol/reconciler.py`, focused Control repository/sink tests | logical terminal transitions | current-route redispatch after disconnect/reconnect without stale connection authority | reconciler, coordination generation, exact acknowledgement tests |
| Integration and phase documentation | `root` | Phase plan, research note, cross-workstream tests | all workstreams | stable Phase 4 diff and checkpoint | Ruff, format, ty, focused/full pytest, pre-commit, absence searches |

- Integration order: add receipt schema/repository → reusable exact Profile source
  preparation → locked first-add/rearm repository transitions → transition service →
  terminal acknowledgement authority → reconnect-safe Control retry → integrated
  concurrency and stale-report tests.
- Independent review: `hardtack` performs one read-only review against M3/M8/M9/
  M11/M15, focusing on atomic Agent/Profile/Runtime commits, idempotency replay,
  immutable Provider binding, exact terminal acknowledgement, incarnation state
  clearing, lazy provisioning, stale source/report rejection, and reconnect dispatch
  authority. Security, persistence, data-loss, or interface corrections require a
  targeted re-review by the same reviewer.
- Final validation:
  - Focused Agent, add-receipt, AgentRuntime, removal, Runtime Profile resolution,
    transition-service, report-sink, and reconciler tests.
  - `uv run ruff check .`, `uv run ruff format --check .`,
    `uv run ty check --error-on-warning`, and full `uv run pytest -q` in
    `python/apps/azents`.
  - Repository pre-commit, `git diff --check`, migration graph/upgrade/downgrade,
    and exact add/rearm/terminal-field/Provider-route absence searches.
- Scope-drift check: Every behavior maps to M3/M8/M9/M11/M15. This phase must not
  add public API/client contracts, removal coordinator stages, Session-tree cleanup,
  Web behavior, feature enablement, Provider reassignment, automatic add, Runtime
  start-on-add, compatibility fallback, or a second capability/configuration source
  of truth.
- Context checkpoint: Phase 3 supplies exact Runtime/Session resource authority.
  Phase 4 supplies the internal transitions and terminal Control semantics that
  Phase 5 removal and Phase 6 public actions will call. Phase 5 remains responsible
  for irreversible confirmation, interruption, product cleanup, physical deletion
  orchestration, and final `removing → none` completion.
