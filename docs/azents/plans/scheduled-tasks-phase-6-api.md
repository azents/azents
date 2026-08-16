---
title: "Scheduled Tasks Phase 6 Public API Plan"
created: 2026-08-16
tags: [scheduled-task, public-api, openapi, generated-client]
---

# Phase Execution Plan

- Phase: `6/8 — Public API and generated clients`
- Branch/base: `feature/scheduled-tasks-6-api` → `feature/scheduled-tasks-5-lifecycle`
- PR boundary: Add the versioned Scheduled Task Public API, exact service-layer authorization, canonical OpenAPI, and generated Python and TypeScript public clients without adding the Web management interface or E2E journeys.
- Inputs: Phase 5 commit `64a594f6e` with stable Task mutation, Binding authorization, cycle projection, lifecycle cleanup, and started-cycle preservation; confirmed `scheduled-260816/REQ`; accepted ADR-D1 through ADR-D7; approved Design revision 3.
- Deliverables: `/scheduled-task/v1` list/create/get/replace/delete/current-cycle routes; bounded request/response schemas; exact Workspace/Agent/Session/Binding authorization; sanitized not-found/validation/conflict errors; canonical Public OpenAPI changes; regenerated Python and TypeScript public clients; focused route, authorization, schema, OpenAPI, and generated-client validation.
- Non-goals: Web routes/components/tRPC, Storybook, localization, browser E2E/testenv journeys, implicit Session creation, Agent tool aliases, Task revision tokens, lease/cycle/version/provider-message exposure, terminal history, pause/resume/rerun/cancel-current-cycle, compatibility routes, fuzzy lookup, fallback Binding, or lifecycle redesign.
- Interfaces: Public requests select one authorized Workspace, Agent, and existing root Session; optional channel target remains the opaque Binding handle accepted by existing External Channel contracts; mutations call the shared `ScheduledTaskService`; management responses expose Task definition, future eligibility, target projection, canonical Session identity/navigation fields, and sanitized current-cycle progress without internal cycle IDs or Toolkit State versions.
- Approved Design mechanisms: `M11`, `M12`, `M13`
- Authority references: `scheduled-260816/REQ-1`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-9`, `REQ-14`, `REQ-16`; `scheduled-260816/ADR-D1`, D2, D3, D4, D5, D6, D7; approved Design revision 3; current Public API, auth, Chat Session, External Channel Binding, OpenAPI generation, and generated-client contracts.
- Design delta: `None`
- Removal obligations: None; this phase adds the first current Scheduled Task Public API and generated-client surface.
- Absence verification: Search and OpenAPI assertions prove there is one `/scheduled-task/v1` domain with no legacy alias, implicit Session endpoint, Task revision token, internal lease/cycle/provider identifiers, raw HTTP Web integration, or hand-edited generated model.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| API projection and authorization service | `/root` | `services/scheduled_task/**`, scoped repository projection helpers | Phase 5 shared mutation/lifecycle services | exact authorized management projection and stable unavailable errors | service tests for wrong Workspace/Agent/Session/Binding, archived/decommissioning state, exact ID, current cycle |
| Public routes and schemas | `/root` | `api/public/scheduled_task/**`, `api/public/__init__.py` | authorization service | versioned CRUD/current-cycle contract with bounded schemas and sanitized errors | route/schema/OpenAPI tests |
| OpenAPI and generated clients | `/root` | canonical OpenAPI outputs; generated Python and TypeScript public-client outputs | stable routes/schemas | source-generated client methods and models | dump/generate commands, Python and TypeScript checks |
| Independent review | `/root/scheduled-stack-reviewer` | read-only complete Phase 6 diff | stable integrated diff and evidence | authority, exposure, error, generation, and scope-drift verdict | severity-grouped report with exact evidence |

- Integration order: Confirm route and projection conventions → implement service authorization/projection → add schemas and routes → mount the domain → add route and schema tests → dump OpenAPI → regenerate both clients → run generated-client and project checks → absence/scope audit → independent review → corrections → final validation → commit and PR.
- Independent review: `/root/scheduled-stack-reviewer` reviews against Requirements, accepted ADR, approved Design M11/M12/M13, current Public API/auth/External Channel contracts, this plan, and the stable diff. Priority: exact Workspace/Agent/Session/Binding authorization, no internal identity leakage, current-cycle sanitization, shared-service mutation semantics, stable HTTP errors, generated-only client changes, and Phase 7/8 exclusion.
- Final validation: focused Scheduled Task service/API tests; OpenAPI path/schema assertions; `uv run ruff check .`; `uv run ruff format --check .`; `uv run ty check --error-on-warning`; OpenAPI dump; Python public-client generation/checks; TypeScript public-client generation/format/lint/typecheck/build as applicable; docs validation; commit hooks; `git diff --check`.
- Scope-drift check: Confirm complete M11/M12/M13 API/client coverage and no Web UI, E2E, implicit Session, public internal cycle/lease/provider identity, compatibility alias, fallback lookup, new lifecycle behavior, or hand-edited generated code.
- Context checkpoint: Phase 5 PR #1304 is open with commit `64a594f6e`, no review blockers, affected suite 362 passed, independent focused suite 104 passed, and Ruff/format/ty/diff/docs/commit hooks passing. Phase 6 receives stable lifecycle and mutation contracts; Phase 7 receives generated TypeScript client methods and sanitized management projections; Phase 8 retains integrated E2E, validation, spec promotion, and cleanup.
