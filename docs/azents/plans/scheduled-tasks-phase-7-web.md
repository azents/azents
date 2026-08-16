---
title: "Scheduled Tasks Phase 7 Web Management Plan"
created: 2026-08-16
tags: [scheduled-task, web, trpc, storybook]
---

# Phase Execution Plan

- Phase: `7/8 — Web management interface`
- Branch/base: `feature/scheduled-tasks-7-web` → `feature/scheduled-tasks-6-api`
- PR boundary: Add the dedicated Agent Scheduled Tasks management route, generated-client tRPC integration, responsive localized UI, and pure-state stories without adding integrated browser E2E, Living Spec promotion, or feature-plan cleanup.
- Inputs: Phase 6 PR #1305 and commit `2569b34e8` with stable `/scheduled-task/v1` CRUD/current-cycle contracts, generated TypeScript client functions, sanitized projections, and transactional Session/Agent/Binding authority fences; existing Chat Session list/create routes; existing External Channel Session Binding list route.
- Deliverables: `/w/{handle}/agents/{agentId}/scheduled-tasks` navigation and page; ADT container/component/page feature; authorized Task list and detail; create/edit forms for one-time and recurring schedules; existing or newly created Team Session selection; authorized Team/User Session display; optional opaque Binding selection with provider location/label; permanent delete confirmation; current-cycle progress; derived execution/future eligibility; canonical Session navigation; localized responsive loading, empty, error, form, conflict, and destructive states; colocated Storybook stories; generated-client-only tRPC router and cache invalidation.
- Non-goals: transcript or terminal history, Pause, Resume, Rerun, cancel-current-cycle, raw HTTP calls, implicit Scheduled API Session creation, empty User Session creation, Task revision tokens, internal cycle/lease/provider-message/Toolkit State fields, fuzzy lookup, fallback Binding selection, lifecycle changes, browser E2E/testenv journeys, Living Spec promotion, implementation-date marking, or plan cleanup.
- Interfaces: `scheduledTaskV1ListScheduledTasks`, `scheduledTaskV1CreateScheduledTask`, `scheduledTaskV1GetScheduledTask`, `scheduledTaskV1ReplaceScheduledTask`, `scheduledTaskV1DeleteScheduledTask`, and `scheduledTaskV1GetScheduledTaskCycle`; `chat.listAgentSessions`, `chat.listAgentUserSessions`, and `chat.createTeamAgentSession`; `externalChannel.listSessionChannels`; existing Agent-focused shell/sidebar and `createReactContainer` conventions.
- Approved Design mechanisms: `M11`, `M12`, `M13`
- Authority references: `scheduled-260816/REQ-1`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-9`, `REQ-14`, `REQ-16`; `scheduled-260816/ADR-D1` through D7; approved Design revision 3 Public API and Web UI section; current Agent route/navigation, Chat Session, External Channel Binding, generated-client, tRPC, localization, and Storybook contracts.
- Design delta: `None`
- Removal obligations: None; this phase adds the first current Scheduled Task Web management surface.
- Absence verification: Search and route assertions prove one dedicated Scheduled Tasks feature with no transcript copy, raw API fetch, compatibility route, implicit Scheduled API Session creation, internal authority identifiers, lifecycle controls, or Phase 8 E2E/spec work.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Generated-client tRPC boundary | `/root` | `typescript/apps/azents-web/src/trpc/routers/scheduledTask.ts`, `_app.ts` | Phase 6 generated client | typed list/detail/cycle/create/replace/delete procedures and stable expected-error mapping | router typecheck, generated-client import audit, focused tests |
| Feature state and form contracts | `/root` | `features/scheduled-tasks/types.ts`, `schemas.ts`, focused tests | tRPC and existing Session/Binding contracts | ADT state, canonical form normalization, schedule validation, query invalidation contract | focused unit tests, typecheck |
| Responsive management surface | `/root` | `features/scheduled-tasks/{ScheduledTasksPage.tsx,containers/**,components/**}` | state/form contracts | list workspace, detail/progress inspector, create/edit flow, Session/Binding selection, delete confirmation, canonical Session navigation | colocated stories, interaction assertions, responsive review |
| Route, navigation, localization | `/root` | Agent scheduled-tasks App Router page, `AgentFocusedSidebar*`, `messages/{en-US,ko-KR,ja-JP,fr-FR}.json` | stable feature entry point | discoverable dedicated Agent route and natural localized copy | route/build, story/localization checks |
| Independent review | `/root/scheduled-stack-reviewer` | read-only complete Phase 7 diff | stable integrated diff and evidence | M11/M12/M13, generated-client use, UI scope, ADT, cache, localization, responsive, and Phase 8 exclusion verdict | severity-grouped report with explicit commit-ready verdict |

- Integration order: Add phase plan → add generated-client tRPC router → define ADT/form/invalidation contracts → implement container → implement pure UI and stories → add dedicated route and sidebar navigation → localize four supported locales → run focused tests and visual/responsive audit → independent review → corrections → final validation → commit and PR.
- Independent review: `/root/scheduled-stack-reviewer` reviews against Requirements, accepted ADR, approved Design revision 3 M11/M12/M13, current Web conventions, this plan, Phase 6 client contract, and the stable diff. Priority: generated-client-only API access, exact Session/Binding selection, no implicit/fallback authority, correct mutation invalidation, no internal field exposure, calm responsive task workflow, localization, stories, and no Phase 8/spec drift.
- Final validation: focused feature and schema/invalidation tests; Storybook story build or test where configured; `pnpm run format`; `pnpm run lint`; `pnpm run typecheck`; `pnpm run build` for `@azents/web`; generated public-client regeneration/source audit; localization JSON validation; `git diff --check`; repository commit hooks.
- Scope-drift check: Confirm complete Phase 7 Web surface over the Phase 6 contract and no new API, persistence, authority, fallback, transcript/history, lifecycle control, browser E2E, spec promotion, implementation date, or plan cleanup.
- Context checkpoint: Phase 6 PR #1305 is open from `feature/scheduled-tasks-6-api` with commit `2569b34e8`, independent commit-ready review, focused backend 36 passed, generated Python Scheduled client 15 passed, Backend Ruff/format/ty, TypeScript client generation/format/typecheck/build, reproducible generation, semantic OpenAPI scope, diff, and commit hooks passing. Phase 7 receives stable sanitized Task/Session/target/cycle projections; Phase 8 retains deterministic integrated browser E2E, full validation, spec promotion, implementation marking, and plan cleanup.
