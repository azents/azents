---
title: "Runtime Profiles Phase 5 Product UI Plan"
created: 2026-07-31
updated: 2026-07-31
tags: [runtime, profile, frontend, admin, workspace, agent]
---

# Phase Execution Plan

- Phase: `5 — Product UI`
- Branch/base: `feature/runtime-profiles-07-product-ui` →
  `feature/runtime-profiles-06-lifecycle-recreation`
- PR boundary: connect the final Admin and Public Runtime Profile APIs to the Platform Admin,
  Workspace Admin, Agent Admin, and Runtime status surfaces; remove the remaining legacy UI
  assumptions
- Inputs: Provider-owned Pod and Container Profile APIs; Workspace Runtime Profile/default APIs;
  Agent `runtime_profile_id`; desired/applied Runtime configuration status; scoped recreation
  operation APIs
- Deliverables: typed infrastructure Profile management inside the existing Runtime Providers
  workspace; Workspace Runtime Profile catalog, exact infrastructure selection, default management,
  lifecycle/availability, and recreation progress; one Agent Runtime Profile selector with
  missing/blocked guidance; desired/applied/waiting Runtime status presentation; localized copy,
  Storybook states, responsive behavior, and generated-client tRPC integration
- Non-goals: backend or generated-client contract changes, new Runtime lifecycle semantics, E2E
  fixture implementation, living-spec promotion, rollout scheduling, operation cancellation, or
  live infrastructure changes
- Interfaces: components receive discriminated UI state from containers; azents-web reaches the
  Public API only through generated client functions in tRPC routers; generated files remain
  unedited; optimistic Profile/default replacements submit the current server version; recreation
  uses the exact current target version; Agent create/update submits nullable
  `runtime_profile_id`; unavailable selections remain visible and never fall back to another
  Profile
- Removal obligations: no global Runtime Profile, independent Agent Provider picker, Agent
  infrastructure override, inherited restriction, or Apply control remains in product UI, stories,
  messages, or tRPC inputs
- Absence verification: frontend search finds no legacy Profile hierarchy, Agent Provider
  preference, execution-policy Apply, or infrastructure override controls; generated clients are
  consumed without raw internal fetches; TypeScript format, lint, typecheck, build, stories, and
  component tests pass

## User roles and screen flow

1. A Platform Admin selects a Runtime Provider and manages only the Pod or Container Profiles owned
   by that Provider. Compatibility and recreation impact stay in the selected Provider detail.
2. A Workspace Owner opens Workspace Settings, manages the Workspace Runtime Profile catalog,
   selects one exact available infrastructure Profile, sets the creation-time default, and monitors
   scoped recreation.
3. An Agent Admin edits an Agent and selects one Workspace Runtime Profile. Missing and unavailable
   selections remain explicit.
4. An operator inspecting a Runtime sees whether configuration is applied, blocked, not yet
   created, or waiting for recreation, including the desired and applied revision identities.

## UI structure

- Use the existing Admin `MasterDetailLayout` for Provider selection and infrastructure Profile
  inspection instead of adding a disconnected Admin application section.
- Keep Workspace Runtime Profiles as a dedicated settings workspace linked from the existing
  Workspace settings surface; use compact rows plus one editor modal rather than a card dashboard.
- Keep Agent selection inside the existing Profile section of `AgentForm`.
- Render recreation progress as an inline operational region near the affected Profile, with
  bounded item failure detail in a collapsible or scrollable area.
- Collapse master/detail views into a list-then-detail flow on narrow screens while preserving the
  selected Profile and mutation/error state.

| Workstream | Owner | Owned paths | Output | Validation |
| --- | --- | --- | --- | --- |
| Admin infrastructure Profiles | `/root` | `typescript/apps/azents-admin-web/src/features/runtime-providers/**`, Admin runtime Provider tRPC router | typed Pod/Container list, editor, compatibility, recreation | component/container tests, Admin typecheck/build |
| Workspace Runtime Profiles | `/root` | `typescript/apps/azents-web/src/features/runtime-profiles/**`, settings routes, Public runtime Profile tRPC router | catalog/default/editor/recreation operation | stories, component/container tests, responsive render |
| Agent selection | `/root` | Agent form schema/component/container/router and stories | one nullable Workspace Runtime Profile selector | create/edit/unavailable/no-Profile states |
| Runtime status | `/root` | Runtime status presentation and Runtime API tRPC integration | desired/applied/waiting/blocked status | stories and focused tests |
| Localization and visual review | `/root` | azents-web locale messages and Storybook fixtures | natural localized operational copy and real-component screenshots | locale typecheck, desktop/mobile visual inspection |

- Integration order: phase plan → Public/Admin tRPC routers → Workspace catalog/default/editor →
  Agent selector → Admin infrastructure Profile management → Runtime status and recreation
  progress → localization/stories/tests → native-resolution component visual review → full
  TypeScript validation
- Independent review: `hardtack`, focusing on authority boundaries, unavailable-state clarity,
  optimistic versions, exact Provider/Profile identity, recreation scope, and absence of legacy
  controls
- Final validation: `pnpm run format`, `pnpm run lint`, `pnpm run typecheck`, `pnpm run build`,
  focused tests, Storybook renders for required states, frontend legacy search, and
  `git diff --check`
- Scope-drift check: no API schema, backend lifecycle, Provider implementation, migration, testenv
  E2E, living spec, or deployment change
- Context checkpoint: Phase 4 is PR #1049 and has final Runtime Profile, recreation, and
  desired/applied API contracts. This phase starts from a clean descendant branch and owns only
  product UI integration. The following phases remain integrated validation, spec promotion, and
  cleanup.
