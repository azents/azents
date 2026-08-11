---
title: "Optional Managed Runtime Phase 6 Public Contracts"
created: 2026-08-10
tags: [agent, runtime, api, openapi, client, backend]
---
# Phase Execution Plan

- Phase: `6 — Public Runtime contracts and generated clients`
- Branch/base: `azents/runtime-optional-capability-6-public-contracts` →
  `azents/runtime-optional-capability-5-removal`
- PR boundary: Publish the unified read-only Agent Runtime model, dedicated
  administrator add/remove actions, compact Agent Runtime-capability projection,
  OpenAPI schema, and regenerated Python and TypeScript public clients. Web UX,
  product E2E promotion, Living Spec promotion, and plan cleanup remain later
  phases.
- Inputs: Phase 5 commit `3a5c0878e`; confirmed `runtime-260803/REQ`; accepted
  `runtime-260803/ADR-D1`, `ADR-D2`, `ADR-D3`, `ADR-D4`, and `ADR-D5`; approved
  `runtime-260803/DESIGN` revision 3; Phase 4 add/rearm transition service; Phase 5
  privacy-safe impact inventory and durable removal service.
- Deliverables:
  - Agent create/get/list/update responses include compact server-owned Runtime
    capability state and version, Profile configuration state, and contextual
    add/remove availability without inferring capability from Profile or physical
    Runtime presence.
  - Runtime GET is read-only, never ensures a logical or physical Runtime, and
    combines Agent capability/version, Profile selection/availability, optional
    physical/configuration state, privacy-safe aggregate removal impact, optional
    active or completed removal progress, and server-computed add/remove/lifecycle/
    Runner-use actions.
  - Runtime-free and removed Agents with no physical Runtime are represented as
    normal states and never rendered as `NOT_STARTED` solely because a Runtime row
    is absent.
  - Dedicated add accepts the explicit Workspace Runtime Profile, expected
    capability and Profile-selection versions, and idempotency key, then delegates
    to the Phase 4 stopped add/rearm transition.
  - Dedicated remove accepts expected capability and Profile-selection versions,
    an idempotency key, and explicit final destructive confirmation, then delegates
    to the Phase 5 irreversible confirmation transition. Replays return the same
    durable operation and privacy-safe impact.
  - Public removal responses contain aggregate root Session, subagent, Run, and
    queued Runtime-action counts plus bounded operation progress only; they expose
    no Session titles, owners, paths, private identifiers, credentials, or raw
    internal cleanup cursors.
  - OpenAPI and generated Python/TypeScript public clients expose the complete
    public contract and compile successfully.
- Non-goals: Web creation/settings/Workspace UI, destructive dialogs, E2E rollout,
  Living Spec promotion, plan cleanup, Provider protocol changes, removal
  cancellation or rollback, generic Agent patch capability transitions, private
  Session metadata, or a compatibility fallback that ensures Runtime during GET.
- Interfaces:
  - Capability states remain exactly `none`, `managed`, and `removing` with
    `runtime_capability_version` as the transition fence.
  - Generic Agent patch may update `runtime_profile_id` only for `managed`; it
    cannot add/remove capability. Omission leaves the selection unchanged and
    explicit null means managed-unconfigured.
  - Add/remove authorization uses existing Agent-settings administration rules and
    never grants access to private User Session details.
  - Add requires an explicit available Profile and leaves the physical desired
    state stopped. Remove requires `confirmed=true`; there is no preview mutation,
    cancellation, or rollback endpoint.
  - Runtime GET reads existing Agent, removal, and physical/configuration evidence
    only. Lifecycle mutations continue to require a managed Runtime and retain
    stable conflict/error semantics.
  - Action availability is server-computed from authorization, capability state,
    removal state, Profile configuration, physical Runtime state, and Runner
    readiness; clients do not reconstruct it.
- Approved Design mechanisms: `M1`, `M5`, `M6`, `M14`.
- Authority references: `runtime-260803/REQ-1`, `REQ-2`, `REQ-3`, `REQ-5`,
  `REQ-6`, `REQ-7`, `REQ-9`; `runtime-260803/ADR-D1`, `ADR-D2`, `ADR-D3`,
  `ADR-D4`, `ADR-D5`; approved Design revision 3 API and Read Models sections;
  current Agent and Agent Runtime Control/Persistence Specs.
- Design delta: `None`
- Removal obligations:
  - Replace the public assumption that a missing `AgentRuntime` is `NOT_STARTED`
    with capability-aware optional physical state.
  - Remove generic Agent Profile patch as an implicit capability-grant path by
    exposing dedicated add/remove actions and stable action-required conflicts.
  - Replace generated client types that require a physical Runtime in every Runtime
    response.
- Absence verification:
  - Contract tests prove Runtime GET performs no ensure/create/selection resolution
    and returns a valid Runtime-free model when no Runtime row exists.
  - API tests prove generic Agent patch cannot transition capability and add/remove
    are the only public transition routes.
  - Public response-model and schema searches find no private Session identifiers,
    titles, owners, paths, credentials, idempotency keys, lease owners, or internal
    cleanup cursor fields.
  - Regenerated clients contain optional physical Runtime models and dedicated
    add/remove methods, with no stale required-Runtime response signature.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Unified service projection | `root` | `services/agent_runtime/` and focused read-only repository methods | Phase 4 transition and Phase 5 removal evidence | capability-aware read model and server-computed actions without Runtime creation | service tests for none/managed/removing/completed, authorization, and no ensure |
| Agent compact projection | `root` | `services/agent/data.py`, `services/agent/`, `api/public/agent/v1/` | unified capability/action rules | capability/version/Profile status and add/remove availability in Agent responses | create/get/list/update contract tests and generic patch rejection tests |
| Public add/remove routes | `root` | `api/public/agent_runtime/v1/`, transition/removal API adapters | existing settings authorization, Phase 4 add, Phase 5 remove | dedicated idempotent fenced actions and safe errors/responses | authorization, stale version, replay, destructive confirmation, privacy tests |
| OpenAPI and generated clients | `root` | public OpenAPI artifacts, `python/libs/azents-public-client/`, `typescript/packages/azents-public-client/` | stable API schema | regenerated Python and TypeScript public clients | generation, Python client tests/type check, TypeScript public-client typecheck/build |
| Integration and phase documentation | `root` | phase plan and focused API integration tests | all workstreams | stable Phase 6 checkpoint | Ruff, format, ty, focused/full pytest, TypeScript checks, pre-commit, absence searches |

- Integration order: define capability-aware service/read models → add compact Agent
  projection → publish add/remove routes and errors → complete API contract tests →
  dump OpenAPI and regenerate both clients → integration and absence validation.
- Independent review: `hardtack` performs one read-only review against M1/M5/M6/
  M14, focusing on GET non-mutation, capability/version fencing, settings
  authorization, idempotency, irreversible confirmation, privacy-safe removal
  projection, generic patch isolation, optional physical Runtime semantics, and
  generated-contract consistency. Security, privacy, data-loss, or material
  interface corrections require targeted re-review by the same reviewer.
- Final validation:
  - Focused Agent API/service and Agent Runtime API/service/add/removal contract
    tests, including query-count or repository-spy evidence that GET never ensures.
  - Public OpenAPI dump, Python public-client generation/tests/type check, and
    TypeScript public-client generation/typecheck/build.
  - `uv run ruff check .`, `uv run ruff format --check .`,
    `uv run ty check --error-on-warning`, and full `uv run pytest -q` in
    `python/apps/azents`.
  - Relevant TypeScript format/lint/typecheck/build, repository pre-commit,
    `git diff --check`, private-field schema searches, and stale mandatory-Runtime
    client signature searches.
- Scope-drift check: Every behavior maps to M1/M5/M6/M14. This phase must not add
  Web behavior, E2E/spec promotion, cancellation/rollback, new capability states,
  client-computed action authority, GET-side ensure/fallback behavior, private
  Session detail exposure, or a new transition/removal source of truth.
- Context checkpoint: Phase 5 leaves durable active/completed removal evidence and
  retained logical Runtime history. Phase 6 publishes those existing authorities
  as optional, privacy-safe public models and leaves Web consumption to Phase 7.
  Phase 8 remains responsible for E2E promotion, Living Specs, implemented markers,
  and plan cleanup.

## Completion Checkpoint

- Completed behavior:
  - Agent responses publish capability/version, Profile configuration status, and
    contextual add/remove availability.
  - Runtime GET is capability-aware and read-only, represents missing physical
    Runtime state with nullable physical/configuration projections, and exposes
    privacy-safe removal impact/progress plus server-computed actions.
  - Dedicated idempotent add/remove routes delegate to the Phase 4 transition and
    Phase 5 irreversible removal authorities with exact optimistic fences.
  - Generic Agent patch rejects Profile or shell enablement that requires a
    dedicated action while preserving managed-only partial Profile updates.
  - Public OpenAPI and generated Python/TypeScript clients expose the complete
    contract; testenv managed-Runtime consumers explicitly narrow optional physical
    projections.
- Removal and privacy evidence:
  - Focused tests prove Runtime-free and managed-not-created GET paths never call
    Runtime ensure and never synthesize a physical summary.
  - OpenAPI/schema checks prove optional physical Runtime/state and aggregate-only
    removal impact.
  - The service read model projects repository removal operations into a bounded
    privacy-safe progress model before the API adapter.
- Validation evidence:
  - Backend Ruff, format, and `ty`: passed.
  - Backend full pytest: `4164 passed`.
  - Focused public Runtime/Agent contract tests: passed.
  - Generated Python client pytest: `648 passed`; changed Runtime API/model files
    pass targeted `ty`.
  - TypeScript public-client generation, full workspace format/lint/typecheck,
    and Web production build: passed after correcting nullable Runtime
    configuration consumption and Runtime-free Storybook fixtures exposed by the
    initial PR CI run.
  - Testenv and E2E `ty`: passed.
  - Repository pre-commit: passed.
- Independent review: `hardtack` completed read-only review and targeted re-review;
  no Critical or Warning findings remain.
- Scope result: M1/M5/M6/M14 are covered; `Design delta: None`. Web UX, product E2E
  promotion, Living Specs, implemented markers, and plan cleanup remain Phases 7–8.
