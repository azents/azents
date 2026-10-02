---
title: "Historical Memory Phase 5: Settings and Generated Clients"
created: 2026-10-01
updated: 2026-10-01
tags: [memory, api, frontend, settings, clients]
---

# Historical Memory Phase 5: Settings and Generated Clients

## Phase Execution Plan

- Phase: `5/6 — Historical settings and generated clients`
- Branch/base: `feature/historical-memory-5-settings` → `feature/historical-memory-4-memory-vfs`
- PR boundary: add authorized read-only Historical Memory inspection to the existing Agent Memory public API and settings page, with generated public clients, while retaining Saved Memory CRUD and the single existing Memory enablement control
- Inputs: Phase 1 Historical source persistence and query ordering; Phase 4 frozen Historical record/lifecycle semantics and source-link path grammar; confirmed `memory-260930/REQ`; accepted ADR-D5 and ADR-D14; approved Design revision `1`
- Deliverables: paginated Historical Memory list and exact detail routes; Team/current-User scope and lifecycle filtering that remains available while Memory is disabled; opaque stable cursor and optional lexical query; generated Python and TypeScript public clients; Saved/Historical kind navigation in existing Memory settings; read-only grouped Historical cards with source links, search, loading, empty, error, and pagination states; accessibility and regression coverage
- Non-goals: Historical mutation routes or controls, a separate Historical toggle or settings page, per-answer attribution, persistent badges or notifications, Session lifecycle changes, new persistence or migration, Scheduler/discovery changes, Memory VFS changes, E2E/load validation, Living Spec promotion, implementation markers, plan cleanup, deployment, or merge
- Interfaces: `GET /agent/v1/workspaces/{handle}/agents/{agent_id}/historical-memories`; `GET /agent/v1/workspaces/{handle}/agents/{agent_id}/historical-memories/{source_session_id}`; exact scope `team|user`; optional lexical query; opaque cursor and bounded page size; response fields for source ID, scope, current source title, source activity boundary, preparation time, bounded summary, and authorized source-session link
- Approved Design mechanisms: `M13`, `M14`
- Authority references: `memory-260930/REQ-1`, `REQ-2`, `REQ-6`, `REQ-9`; ADR-D5, ADR-D14; current Agent, Memory, Session lifecycle, public API, and frontend settings constraints
- Design delta: `None`
- Removal obligations: replace the Saved-only settings content area with Saved + read-only Historical kinds in the same surface; retain existing Saved routes, generated operations, Agent/User scopes, global Memory enable switch, and create/edit/delete behavior
- Absence verification: public OpenAPI and generated clients expose only GET operations for Historical Memory; Historical UI renders no create/edit/delete/archive/toggle/badge/notification/per-answer controls; Saved CRUD and the existing Memory enable switch remain covered; no Phase 6 Specs/E2E/load/activation changes enter the diff

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase contract | `/root` | `docs/azents/plans/historical-memory-phase-5-settings.md` | Phase 4 checkpoint | Frozen scope, interfaces, removals, validation, and drift boundary | Docs validation, diff check |
| Historical settings query contract | `/root` | Historical repository settings query/data and focused PostgreSQL tests | Existing Historical source/session/Agent/Workspace/member schema | Stable cursor-paginated Team/current-User inventory and exact detail with active-source authorization, lexical query, bounded summaries, and no Memory-enabled predicate | Repository tests for scope, membership, disabled Agent visibility, archive/purge, ordering, cursor validation/stability, query, and bounds |
| Public service and API | `/root` | Memory/Historical settings service data, Agent public routes/data, focused service/route/schema tests | Settings repository contract and existing Agent visibility rules | Non-enumerating list/detail API with generated OpenAPI schemas and authorized source links | Service/API tests for visible/private Agent, Workspace mismatch, invisible source, malformed cursor, disabled Memory, and uniform 404 behavior |
| Generated public clients | `/root` | public OpenAPI spec and generated Python/TypeScript public clients | Stable public route/schema | Source-generated list/detail operations and response models | OpenAPI dump, Python client generation/tests, TypeScript generation/typecheck, read-only operation absence search |
| Memory settings container and bridge | `/root` | `typescript/apps/azents-web/src/trpc/routers/agent.ts`, Agent Memory settings container/types | Generated TypeScript client | Separate Saved/Historical kind and scope/query/page states without coupling mutation controls into Historical mode | tRPC typecheck and container/state tests; Saved mutation invalidation regressions |
| Memory settings presentation and localization | `/root` | Agent Memory settings component/stories and `workspace.json` locales | Container contract and source link grammar | Existing-page Saved/Historical selector; grouped Team/My Historical cards; accessible source links; loading/error/empty/search/pagination states; no Historical mutations | Storybook interaction assertions, locale structure tests, web test/lint/typecheck/build |
| Integrated privacy and regression | `/root` | Focused cross-layer tests only | All Phase 5 workstreams | End-to-end API-to-component contract with Saved CRUD preserved and Historical read-only/privacy semantics enforced | Focused suites, full backend, full web checks, OpenAPI/client no-drift, absence searches |

- Integration order: phase plan → repository query/data → service outputs and authorization → API schemas/routes/tests → OpenAPI and generated clients → tRPC bridge/container → presentation/localization/stories → integrated validation and absence checks
- Independent review: `/root/historical-memory-reviewer`; `/root` requests one read-only review only after all backend, generated-client, and frontend work is integrated, the diff is stable, and root validation passes
- Final validation: root runs docs validation and `git diff --check`; backend Ruff/format, whole-subproject typecheck, focused repository/service/API tests, full backend pytest, migration suite, OpenAPI generation; Python and TypeScript public-client generation/consistency checks; TypeScript format, lint, typecheck, web tests, build, and Storybook/accessibility checks where configured; source searches proving Historical operations are read-only, Historical UI has no mutation controls, Saved CRUD remains, and Phase 6 paths are unchanged
- Scope-drift check: implement only M13/M14 and the approved REQ-9 inspection surface; settings reads deliberately omit the VFS root-session and Memory-enabled gates while preserving Agent visibility, current Workspace membership, exact Team/current-User scope, active source lifecycle, and non-enumeration; omit new controls, persistence, background behavior, model behavior, Specs, E2E/load, compatibility aliases, and unapproved failure modes
- Context checkpoint: Phase 4 provides a reviewed live Memory VFS and final model-facing tool cutover at commit `418557da7` with PR #2037; Phase 5 consumes existing Historical rows but introduces no migration; the primary risks are accidental Memory-disabled hiding, personal-scope leakage, cursor drift/enumeration, Saved CRUD regression, and generated/localization drift; Phase 6 remains responsible for integrated E2E/load, activation, Spec promotion, implementation markers, and plan cleanup
