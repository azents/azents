---
title: "Optional Managed Runtime Phase 7 Web UX"
created: 2026-08-10
tags: [agent, runtime, workspace, web, frontend]
---
# Phase Execution Plan

- Phase: `7 — Web UX`
- Branch/base: `azents/runtime-optional-capability-7-web-ux` →
  `azents/runtime-optional-capability-6-public-contracts`
- PR boundary: Consume the unified server Runtime contract in Agent creation,
  settings, Workspace, and shared directory-picker surfaces; add explicit
  profile-backed Runtime addition, irreversible aggregate-only removal confirmation
  and progress, and capability-aware query/control gating without adding new backend
  authority.
- Inputs: Phase 6 public Runtime read/add/remove contracts and generated TypeScript
  client; confirmed `runtime-260803/REQ`; accepted `runtime-260803/ADR-D5` and
  `ADR-D6`; approved `runtime-260803/DESIGN` revision 3.
- Deliverables:
  - Agent creation presents `No Runtime` as the visible default, explains retained
    model/remote capabilities and Runtime-provided shell/filesystem/Workspace/Project/
    Git/build/test authority, and keeps available Runtime Profile selection direct.
  - Agent settings exposes one dedicated Runtime area driven by `capability`, Profile
    status, removal impact/progress, and server-computed actions.
  - Runtime-free administrators can select an available Profile and explicitly
    confirm Runtime addition; addition remains configured and stopped until use.
  - Managed administrators can inspect/update Profile configuration, distinguish
    temporary lifecycle controls from permanent removal, and explicitly confirm
    irreversible removal after reviewing deleted, retained, and aggregate interrupted
    work impact.
  - Removing state exposes bounded stage/progress and aggregate counts only, with no
    cancellation, re-add, paths, Session metadata, actors, keys, cursors, leases, or
    authority fields.
  - Workspace navigation remains visible for `none` and `removing`, renders distinct
    capability-aware empty/progress states, offers contextual navigation to Add
    Runtime only when `actions.add` allows it, and never maps absent physical Runtime
    to `NOT_STARTED`.
  - Workspace, Project, Git, file, directory-picker, and lifecycle queries/mutations
    are enabled only for the server-authorized managed state/action.
  - Runtime-dependent settings such as shell execution guide Runtime-free admins to
    the dedicated add flow instead of submitting a generic capability transition.
- Non-goals: Backend/API schema changes, generated-client edits, new capability
  identifiers or states, automatic Runtime addition, removal cancellation/rollback,
  Session-specific Runtime selection, product E2E promotion, Living Spec promotion,
  rollout enablement, or plan cleanup.
- Interfaces:
  - `chat.getAgentRuntime` is the sole Web Runtime state/action source.
  - New tRPC `addAgentRuntime` and `removeAgentRuntime` wrappers call only generated
    SDK actions and pass exact capability/Profile-selection versions plus one browser
    idempotency key per submitted transition.
  - Generic `agent.update` remains limited to managed Profile configuration and
    non-capability settings; it never adds/removes Runtime.
  - Removal UI consumes only `removal_impact` aggregate counts and bounded
    `removal` status/stage/counters.
  - Runtime polling runs only while capability is `removing` or configuration is in
    an existing bounded transition state and stops on terminal/non-transition state.
- Approved Design mechanisms: `M5`, `M6`, `M14`.
- Authority references: `runtime-260803/REQ-1`, `REQ-2`, `REQ-4`, `REQ-5`,
  `REQ-6`, `REQ-7`, `REQ-8`, `REQ-9`; `runtime-260803/ADR-D5`, `ADR-D6`;
  approved Design revision 3.
- Design delta: `None`
- Removal obligations:
  - Replace Web inference of missing physical Runtime as `NOT_STARTED` with explicit
    Runtime-free/removing UI state.
  - Remove generic Agent Profile patch as a Runtime capability transition path.
  - Replace hidden/unusable Workspace behavior for Runtime-free/removing Agents with
    stable capability-aware surfaces.
  - Remove stale UI controls and queries that remain active when server Runtime
    actions/capability deny them.
- Absence verification:
  - Repository searches find no Web add/remove capability mutation through
    `agent.update` and no physical `runtime === null` → `NOT_STARTED` mapping.
  - Runtime-free/removing stories prove no workspace/file/project query-dependent
    controls are rendered as usable.
  - Removal stories and locale copy contain no Session metadata, paths, actors, keys,
    cursors, lease or authority identifiers, or cancellation/re-add action.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Runtime tRPC and settings state | `root` | `src/trpc/routers/chat.ts`, `features/agents/AgentRuntimeSettingsPage.tsx`, `features/agents/containers/useAgentRuntimeSettingsContainer.ts` | Phase 6 generated SDK | Add/remove wrappers, ADT state, exact invalidation and bounded polling | Typecheck, lint, focused tests |
| Runtime settings and creation guidance | `root` | `features/agents/components/{AgentRuntimeSettings,AgentSettingsHub,AgentForm,AgentDangerSection}.tsx`, settings route/page integration | Runtime settings state | Dedicated add/manage/remove flow and guided shell/Profile UX | Storybook stories, component tests |
| Workspace capability states | `root` | `features/chat/workspace/{types.ts,containers/useWorkspacePanelContainer.ts,components/WorkspacePanel.tsx,components/RuntimeActivationView.tsx}`, `features/agent-workspace/{types.ts,containers/useAgentWorkspaceDirectoryPickerContainer.ts,components/AgentWorkspaceDirectoryPickerModal.tsx}` | Unified Runtime query/actions | Runtime-free and removal progress states; query/control gating | Workspace and picker stories, focused tests |
| Localization and integration | `root` | `messages/{en-US,fr-FR,ja-JP,ko-KR}.json`, affected stories/tests | All UI workstreams | Natural localized utility copy and stable responsive states | JSON format, locale checks, Storybook build |

- Integration order: tRPC add/remove wrappers → Runtime settings ADT/container → pure
  settings component and route/hub → creation/capability guidance → Workspace and
  directory-picker query gating/state rendering → stories/locales → integration
  validation.
- Independent review: `hardtack` reviews the complete Phase 7 diff against
  M5/M6/M14, focusing on server action authority, irreversible confirmation,
  aggregate-only privacy, no generic capability patch, correct `none`/`managed`/
  `removing` distinctions, bounded polling, and disabled Runtime-dependent queries.
  Security, privacy, data-loss, or material interface corrections require targeted
  re-review by the same reviewer.
- Final validation:
  - `pnpm --filter @azents/web lint`
  - `pnpm --filter @azents/web typecheck`
  - `pnpm --filter @azents/web test`
  - `pnpm --filter @azents/web format:check`
  - `pnpm --filter @azents/web build-storybook`
  - Repository pre-commit, `git diff --check`, and exact absence/privacy searches.
- Scope-drift check: Every user-visible behavior maps to M5/M6/M14 and the confirmed
  Requirements. The phase adds no client-owned permission table, capability state,
  fallback authority, automatic provisioning, cancellation, rollback, private
  Session detail, generated-client edit, backend contract, or Phase 8 promotion.
- Context checkpoint: Phase 6 supplies nullable physical Runtime/configuration,
  exact Agent capability/Profile versions, privacy-safe removal projections, and
  complete server actions. Phase 7 consumes those authorities in Web only. Phase 8
  remains responsible for product E2E, rollout validation, Specs/implemented markers,
  and plan cleanup.
