---
title: "Immediate External Channel Provider Delivery Phase 2 Execution Plan"
created: 2026-08-02
tags: [external-channel, slack, discord, backend, frontend, migration]
---

# Phase Execution Plan

- Phase: `2 — Atomic direct-execution cutover`
- Branch/base:
  `feat/immediate-provider-delivery-cutover` →
  `feat/immediate-provider-delivery-foundation@9a10f88d1`
- PR boundary: Replace the complete External Channel Action/Delivery Attempt
  authority with direct Tool and post-commit execution, owner-local current
  projection state, and the coordinated schema/API/Web contract cutover.
- Inputs:
  - confirmed `channel-260802/REQ`;
  - accepted `channel-260802/ADR`;
  - approved `channel-260802/DESIGN` revision 1 and mechanisms `M1`–`M12`;
  - Phase 1 process-local provider contracts at `9a10f88d1`; and
  - current External Channel domain, delivery, authorization, lifecycle, and E2E
    strategy Specs.
- Deliverables:
  - ordinary synchronous `channel_action` execution with canonical Work commit,
    ordered direct provider effects, and identifier-free immediate outcomes;
  - direct post-commit/post-response non-Tool provider controls that never gate
    canonical admission, wake, AgentRun, or terminal lifecycle state;
  - owner-local Work projection parts and access-control current projection state;
  - removal of Action/Delivery repositories, recovery, Worker, engine, lifecycle,
    finalizer, management-history, generated-client, and Web dependencies;
  - one generated destructive Alembic migration with no history backfill or
    compatibility path; and
  - focused backend, migration, API/client, and Web tests for the cutover.
- Non-goals:
  - deterministic end-to-end journey expansion;
  - Living Spec promotion or implementation-date recording;
  - plan cleanup;
  - deployment, live provider mutation, or PR merge;
  - retry, replay, compensation, recovery, compatibility, feature-flag, or
    mixed-version modes.
- Interfaces:
  - `channel_action` input remains unchanged;
  - Tool output is binding/state/state revision plus ordered outcomes containing
    operation, part, status, and optional safe reason/detail only;
  - provider effects classify `delivered | failed | unknown | not_attempted`;
  - provider message identities remain internal current projection state and never
    enter Tool results;
  - non-Tool control outcomes cannot change already committed canonical state;
  - `ManagedDelivery` and `ManagedBinding.deliveries` are removed while current Work
    projection fields remain owner-derived;
  - generated clients change only through OpenAPI regeneration; and
  - the application and destructive migration are one coordinated cutover.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`,
  `M9`, `M10`, `M11`, `M12`
- Authority references: `channel-260802/REQ-1` through `REQ-7`,
  `channel-260802/ADR-D1`, `channel-260802/ADR-D2`, approved Design revision 1,
  unchanged current authorization/file/lifecycle Specs, and repository migration and
  generated-client conventions.
- Design delta: `None`
- Removal obligations: All Design Removal and Replacement entries except Living Spec
  promotion and temporary plan cleanup, which remain Phase 3 responsibilities.
- Absence verification:
  - schema tests prove both tables, dependent foreign keys/indexes, and delivery-only
    PostgreSQL enums are absent after upgrade;
  - repository searches find no Action/Delivery model, data, query, service, Worker,
    engine recovery, lifecycle intent, finalizer count, or compatibility reference;
  - generated-client and Web searches find no `ManagedDelivery`, `deliveries`, or
    Delivery UI surface; and
  - runtime tests prove no background drain, pending query, replay, or second
    provider mutation authority remains reachable.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Direct Tool and provider effects | Primary agent | `python/apps/azents/src/azents/services/external_channel/{channel_action.py,provider_effect.py,presentation.py,discord_delivery.py}`; `python/apps/azents/src/azents/repos/external_channel/{work.py,work_data.py}`; `python/apps/azents/src/azents/engine/tools/external_channel.py`; focused tests | Phase 1 contracts | Canonical commit plus ordered direct execution and immediate Tool outcomes | Focused Ruff, Pyright, repository/service/engine tests |
| Direct controls and lifecycle | Primary agent | External Channel admission, ingestion, interaction, participation, access, provider-control, connection, lifecycle, archive/purge/finalizer services and repositories; Worker composition; focused tests | Direct provider executor and owner-local state | One-shot post-commit controls, in-memory terminal cleanup, no Worker/recovery authority | Focused service, lifecycle, worker, archive, and finalizer tests |
| Persistence and migration | Primary agent | `python/apps/azents/src/azents/rdb/models/external_channel.py`; `python/apps/azents/db-schemas/rdb/**`; repository data models and migration tests | Stable owner-local projection schema | Generated destructive revision, current-state migration, removed legacy tables/types | Upgrade/downgrade, populated-schema, enum/FK/table absence tests |
| Management and generated clients | Primary agent | management repository/service/API schemas and routes; dumped OpenAPI; generated Python/TypeScript public clients and tests | Stable backend contract | Current Work-only management contract without delivery history | API contract tests, generation commands, Python/TypeScript type checks |
| Web cutover | Primary agent | `typescript/apps/azents-web/src/features/session-channels/**` and related stories/translations/tests | Generated TypeScript public client | Session Channels without Delivery section while current Work projection remains | Format, lint, typecheck, build, focused component/story checks |
| Integration and plans | Primary agent | Phase plan, shared composition, absence audit, branch/PR metadata | All workstreams | One atomic reviewable cutover diff and checkpoint | Full validation matrix and `git diff --check` |

- Integration order:
  1. Replace repository Action/Delivery planning with canonical Work transition and
     process-local effect plans while establishing owner-local projection fields.
  2. Convert `channel_action` and non-Tool callers to the shared direct executor;
     retain live authority and file-transfer validation.
  3. Replace lifecycle cleanup IDs with in-memory plans, then remove Worker, engine
     recovery, idle settlement, finalizer, and purge dependencies.
  4. Remove ORM/data/query surfaces and generate the new Alembic revision against the
     stable cutover models; add populated upgrade/downgrade tests.
  5. Remove management delivery history, dump OpenAPI, regenerate both public
     clients, and adapt Web Session Channels.
  6. Run focused checks, repository-wide absence searches, full backend and
     TypeScript validation, and scope-drift audit.
  7. Correct required findings, request `hardtack` review on the stable PR, and
     record the Phase 2 checkpoint before Phase 3.
- Independent review:
  - reviewer: GitHub reviewer `hardtack`;
  - scope: complete Phase 2 diff against `channel-260802/REQ`, ADR-D1/D2, approved
    Design revision 1, Phase 1 contracts, current Specs, and this plan;
  - criteria: one delivery authority, canonical commit independence, no provider
    replay/recovery, correct owner-local projection CAS, safe file authorization,
    destructive migration correctness/data-loss boundary, no legacy API/UI/generated
    surface, and no secret/provider payload exposure;
  - inputs: authoritative documents, phase plans, complete diff, migration and
    generation artifacts, validation results, and absence searches;
  - output: grounded Critical/Warning findings or explicit no findings; targeted
    re-review only for Requirements/Design, security/data-loss, or material
    convention/interface corrections.
- Final validation:
  - `cd python/apps/azents && uv run ruff check --fix .`
  - `cd python/apps/azents && uv run ruff format .`
  - `cd python/apps/azents && uv run pyright`
  - focused External Channel, engine, worker, lifecycle, purge/finalizer, management,
    and migration tests
  - `cd python/apps/azents && uv run pytest`
  - `cd python/apps/azents && uv run python src/cli/dump_openapi.py`
  - `cd python/libs/azents-public-client && make generate`
  - `cd typescript && pnpm run generate --filter=@azents/public-client`
  - `cd typescript && pnpm run format && pnpm run lint && pnpm run typecheck`
  - `cd typescript && pnpm run build`
  - repository-wide legacy symbol/schema/UI absence searches
  - `git diff --check`
- Scope-drift check:
  - verify every M1–M12 mechanism and every Phase 2 removal obligation is present;
  - reject any new persistence, queue, retry, replay, recovery, fallback,
    compatibility, runtime mode, setting, history, or second authority;
  - keep deterministic E2E expansion, Living Spec promotion, implementation dates,
    and plan cleanup in Phase 3; and
  - return any material behavior/state/interface mechanism outside approved Design
    authority to feature design before continuing.
- Context checkpoint: Record completed direct behavior, owner-local schema and API
  interfaces, generated artifacts, migration revision/base, validation and absence
  evidence, review findings, remaining Phase 3 E2E/spec work, exact Phase 3 base
  commit, risks, and blockers.
