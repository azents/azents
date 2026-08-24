---
title: "Runtime System Metrics Phase 2 Product UI and Verification"
created: 2026-08-24
updated: 2026-08-24
tags: [runtime, metrics, implementation, frontend, e2e, spec]
---

# Runtime System Metrics Phase 2 Product UI and Verification

## Phase Execution Plan

- Phase: `2/2 — Product UI, E2E, Specs, and completion`
- Branch/base: `feat/runtime-system-metrics-2-product-ui` → `feat/runtime-system-metrics-1-runtime-api` / PR #1462
- PR boundary: generated-client-backed product presentation in chat and Runtime settings, required Docker Runtime browser verification, Living Spec promotion, implementation markers, and temporary-plan cleanup.
- Inputs: opened Phase 1 PR #1462 with stable Runner/Control/store/API/OpenAPI contracts; confirmed `runtime-260824/REQ`; accepted `runtime-260824/ADR-D1` through `ADR-D7`; approved `runtime-260824/DESIGN` revision `1`.
- Deliverables: M5–M8 web query, shared responsive metrics overview, stories/tests, visibility-scoped polling, lifecycle invalidation, required Docker Runtime E2E, Spec promotion, matching implementation markers, and plan cleanup.
- Non-goals: Provider, Admin, database, migration, chart, configuration, push transport, alerting, browser-owned history, interpolation, configurable cadence, or any second API/wire contract.
- Interfaces: generated `agentRuntimeV1GetAgentRuntimeSystemMetrics`; one tRPC query keyed by Workspace handle and Agent ID; fixed 60-second refetch only while the owning surface is visible; shared component states derived only from `AgentRuntimeSystemMetricsResponse`; no raw Runtime or infrastructure identifiers.
- Approved Design mechanisms: `M5`, `M6`, `M7`, `M8`, with integration verification for `M1` through `M8`.
- Authority references: `runtime-260824/REQ-1` through `REQ-6`; `runtime-260824/ADR-D1` through `ADR-D7`; `runtime-260824/DESIGN` revision `1`; current Agent Runtime Persistence and Workspace Specs; generated-client, localization, responsive UI, Storybook, deterministic test, and no-direct-DB-write conventions.
- Design delta: `None`
- Removal obligations: remove the feature implementation plans only after product validation and Spec promotion. No product implementation replacement is required.
- Absence verification: final diff contains no Provider/Admin/database/chart/configuration path, raw API client call, browser sample accumulator/interpolator, direct DB E2E setup, second metrics endpoint, or lifecycle-response expansion. Generated client is the only web API contract.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Web API boundary | `/root` | `typescript/apps/azents-web/src/trpc/routers/chat.ts`; generated client imports | Phase 1 OpenAPI | Generated-client-backed metrics query and expected error mapping | Web lint/type tests; no raw HTTP path |
| Shared metrics UI | `/root` | `typescript/apps/azents-web/src/features/runtime-metrics/**`; locale message files | Web query contract | Responsive three-metric overview, SVG trends with gaps, complete explicit states and utility copy | Component tests/stories, Storybook build or focused story validation, responsive review |
| Chat integration | `/root` | `features/chat/workspace/**` | Shared UI/query | Overview above Runtime/Workspace content with `autoRefreshVisible` polling gate | Container/component tests and stories |
| Settings integration | `/root` | `features/agents/**` | Shared UI/query | Same overview near Runtime status, polling while mounted, lifecycle invalidation | Container/component tests and stories |
| Required E2E | `/root` | `testenv/azents/e2e/src/tests/web/public/**` | Product UI and Docker Runtime fixture | Real Runner metrics in chat/settings, panel reopen, stopped state, access/capability evidence where fixture-supported | Focused Selenium E2E with existing Docker Provider fixture; no direct DB writes |
| Specs and completion | `/root` | `docs/azents/spec/**`; approved snapshot frontmatter; `docs/azents/plans/**` | Stable validation | Current Specs, matching `implemented: 2026-08-24`, complete M1–M8 drift record, temporary-plan removal | `/spec-review`, docs validation, absence audit |

- Integration order:
  1. Add generated-client-backed tRPC query.
  2. Implement the pure shared overview and complete static stories.
  3. Integrate chat and settings containers with visibility/polling and mutation invalidation.
  4. Add focused unit/story checks and responsive visual verification.
  5. Extend the existing Docker Runtime web E2E journey through product APIs/UI.
  6. Run complete affected validation and M1–M8 drift/absence audit.
  7. Run Spec review, promote Specs and implementation markers, then remove all feature plans.
  8. Request read-only review, commit, and open PR 2/2 against Phase 1.
- Independent review: `runtime-metrics-reviewer` reviews the stable Phase 2 diff read-only against Requirements, ADR-D1–D7, Design revision 1 M1–M8, both phase contracts, generated-client use, UI state fidelity, localization/responsiveness, polling scope, E2E fixture authenticity, Spec accuracy, plan cleanup, privacy, and unauthorized scope. Only requirements/design, security/data-loss, or material interface corrections require targeted re-review.
- Final validation: filtered azents-web format/lint/typecheck/build and focused tests/stories; generated public client check; testenv E2E Ruff/type and focused Docker Runtime web test; relevant backend/Runner checks if Phase 1 code changes; docs index/snapshot validation; `/spec-review`; `git diff --check`; complete stack comparison.
- Scope-drift check: approved Phase 2 behavior is shared UI, generated-client query, visibility-scoped polling, lifecycle refresh, real Docker Runtime E2E, and Spec completion. Unauthorized additions are Provider/Admin/database/infrastructure/configuration, alerting/push, browser history authority, interpolation, alternate API paths, or changes to Phase 1 runtime semantics.
- Context checkpoint: pending. Before PR, record rendered states, query/polling behavior, E2E evidence, Spec changes, implementation markers, plan removal, validation commands, review result, remaining risks, and complete M1–M8/absence evidence.
