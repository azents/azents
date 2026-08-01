---
title: "Workspace Settings Hub Design"
created: 2026-08-01
updated: 2026-08-01
implemented: 2026-08-01
tags: [workspace, settings, frontend, architecture]
document_role: primary
document_type: design
snapshot_id: workspace-260801
---

# Workspace Settings Hub Design

- Requirements: [workspace-260801/REQ](../requirements/workspace-260801-settings-hub.md)
- ADR: [workspace-260801/ADR](../adr/workspace-260801-settings-hub.md)
- Design reference: `workspace-260801/DESIGN`
- Mode: Autonomous

## Summary

Replace the combined Workspace LLM settings page with a Workspace settings overview and two focused detail pages. The overview and details use a Workspace-specific identity header and the same structural settings pattern as Agent settings. A domain-independent shared layout primitive keeps the common header/return-bar/content boundary consistent while Agent and Workspace wrappers retain their own data, translations, and navigation ownership.

The implementation preserves the existing public APIs, stored configuration, Workspace membership permissions, Owner-only management behavior, provider credential flows, model validation, catalog synchronization, and subscription usage behavior.

## Current Behavior and Gaps

| Area | Current behavior | Requirement gap |
| --- | --- | --- |
| Settings entry | `/w/{handle}/settings` renders `LlmSettingsPage` directly. | There is no overview or scalable Workspace settings information architecture. |
| Page composition | `LlmSettings` renders Workspace model defaults followed by LLM integration cards and one shared modal. | Default model configuration and provider credential management are unrelated tasks on one surface. |
| State ownership | `useLlmSettingsContainer` waits for integration list, provider capabilities, and Workspace model settings together and exposes one mutation state. | A failure or loading state for one task can block the other task after route separation. |
| Settings shell | Workspace pages use `WorkspaceShell`; there is no Workspace settings header or return bar. | Workspace settings does not match the established Agent settings hierarchy. |
| Workspace identity | The route receives only `handle`; `AppBar` shows the handle but the settings content does not identify the Workspace by name. | Overview and direct detail entry need a meaningful Workspace identity. |
| Test coverage | Existing Storybook coverage targets the combined `LlmSettings`; no Workspace settings route E2E was found. | The new navigation, focused states, and read-only behavior need direct verification. |

## Proposed Architecture

### Route Contract

Implement `workspace-260801/ADR-D1` with these routes:

| Route | Responsibility |
| --- | --- |
| `/w/{handle}/settings` | Workspace settings overview |
| `/w/{handle}/settings/models` | Workspace default model settings |
| `/w/{handle}/settings/llm-integrations` | LLM provider integration management |

`settings/page.tsx` remains a thin entrypoint. A new `settings/[section]/page.tsx` parses an allowlist containing only `models` and `llm-integrations`; every other value calls `notFound()`.

Both route entrypoints load the current Workspace through server tRPC and pass a typed `WorkspaceResponse` to a feature Page component. `TRPCError` with `NOT_FOUND` maps to `notFound()`. The parent `/w/{handle}` layout remains the membership gate, and the `(workspace)` route group remains the visual shell owner.

The previous behavior where `/settings` rendered the combined LLM page is removed. No redirect, query flag, or legacy route retains the combined surface.

### Workspace Identity Data

The backend and generated public client already expose `GET /workspace/v1/workspaces/{handle}`. Add `workspace.get` to `src/trpc/routers/workspace.ts` using the existing generated `workspaceV1GetWorkspaceByHandle` operation and map `401`, `403`, and `404` to the corresponding tRPC errors.

This is a frontend integration wrapper over an existing public API, not a new backend contract or persistence change.

### Shared Settings Layout Boundary

Implement `workspace-260801/ADR-D2` by adding a shared `SettingsPageLayout` component under `src/shared/components/`.

The shared primitive owns only:

- a caller-provided header slot;
- a caller-provided return href and label;
- the return bar, arrow action, maximum width, border, and background;
- the full-height flex boundary and a `minHeight: 0` content slot that permits the task surface to own scrolling.

The shared primitive does not import feature modules, read translations, fetch data, or know about Agent and Workspace types.

Refactor `AgentSettingsLayout` to render the shared primitive with `AgentSettingsHeader` and its existing translated return target. Preserve its public props and the existing widths so Agent settings behavior and call sites do not change.

Add `WorkspaceSettingsLayout` under a new `features/workspace-settings/` feature. It renders:

- `WorkspaceSettingsHeader` with Workspace name and `@handle`;
- a return action to the Workspace root for the overview;
- a return action to `/w/{handle}/settings` for detail pages; and
- the shared settings page layout primitive.

The Workspace header does not use Agent mobile navigation. `WorkspaceShell` and the global AppBar continue to own the Workspace sidebar drawer on mobile.

### Settings Overview

Add a prop-driven `WorkspaceSettingsHub` component and Page wrapper.

The overview uses the established Agent settings visual pattern:

- calm page title and task-oriented description;
- grouped, bordered row navigation rather than a card mosaic;
- icon, label, description, and chevron per row;
- a maximum content width aligned with the Agent settings hub; and
- one scrollable task surface inside the settings layout.

The initial overview contains one configuration group with two rows:

1. **Default models** → `/settings/models`
2. **LLM integrations** → `/settings/llm-integrations`

It does not duplicate Members, Toolkits, External channels, Runtime execution, or My Profile.

### Focused Model Settings Page

Add `WorkspaceModelSettingsPage`, `WorkspaceModelSettings`, and `useWorkspaceModelSettingsContainer`.

The container owns:

- `workspaceMember.me` for existing Owner-only presentation;
- `llmProviderIntegration.list` for provider integration options;
- `workspaceModelSettings.get` for stored Workspace defaults;
- `llmProviderIntegration.syncCatalog`;
- `workspaceModelSettings.update`; and
- independent model-page query and mutation ADTs.

The pure UI renders a focused heading and the existing `WorkspaceModelSettingsCard`. The card retains its current form synchronization, validation, selectable model editor, read-only behavior, catalog synchronization, and save action.

The page must not query provider capabilities or initialize integration CRUD/modal state because those are not required for model configuration.

### Focused LLM Integrations Page

Replace the combined `LlmSettings` composition with `LlmIntegrationsPage`, `LlmIntegrations`, and `useLlmIntegrationsContainer`.

The container owns:

- `workspaceMember.me` for existing Owner-only presentation;
- `llmProviderIntegration.list`;
- `llmProviderIntegration.listProviders`;
- create, update, delete, toggle, and catalog invalidation behavior;
- the integration form modal state; and
- an integration-specific mutation ADT.

The Page wrapper continues to compose `SubscriptionUsageContainer` for each integration. Existing `IntegrationFormModal`, provider credential forms, OAuth connection components, usage summaries, provider labels, status badges, and integration card behavior remain authoritative.

The pure UI renders only the LLM integration heading, add action, description, integration states/cards, and form modal. It does not render or query Workspace model settings.

### State and Cache Behavior

Implement `workspace-260801/ADR-D3` with separate discriminated unions:

- `WorkspaceModelSettingsState`: `LOADING`, `ERROR`, or `READY` with model settings and provider options.
- `LlmIntegrationListState`: `LOADING`, `ERROR`, or `READY` with integrations.
- focused mutation state types where each error belongs to the action surface that can display it.

The two containers may use the same tRPC integration-list query key. tRPC query cache is the shared server-state authority during navigation; no custom React context or manually synchronized cross-route cache is introduced.

Pure helper functions and input types for provider configuration may move to query-independent modules if both containers need them. Hooks, mutation objects, and modal state are not shared.

## Permissions and Security

- The parent Workspace layout continues to enforce authenticated Workspace membership.
- Both settings detail containers continue to derive `canManage` from `workspaceMember.me.role === "owner"`.
- Read-only members can view current model and integration state.
- Owner-only buttons, switches, edit/delete actions, and save actions remain hidden or disabled exactly according to the focused component contract.
- Backend authorization remains final. The UI does not infer new permissions or bypass API failures.
- Provider secrets remain handled through the existing generated client and integration mutation paths. No secret is added to route parameters, logs, stories, or persisted browser state.

## Loading, Error, Empty, and Responsive Behavior

- The Workspace identity header and return action render from server-loaded Workspace data before client queries begin.
- Each detail page shows only its own loading and error state.
- The integrations page preserves the existing explicit empty state and add action for Owners.
- Read-only pages do not show controls that imply an unavailable mutation.
- The content slot uses `minHeight: 0`; each hub/detail surface owns one overflow container to avoid nested page scrolling.
- Desktop content uses the same restrained maximum widths as Agent settings.
- Mobile retains the Workspace AppBar/sidebar drawer and shows a compact Workspace identity header without adding a second navigation drawer control.
- Long Workspace names, handles, integration names, status badges, and descriptions truncate or wrap without displacing the return action.

## Localization

Add Workspace settings layout, overview, detail heading, row label, row description, return action, and accessibility strings to all supported locale files:

- `messages/en-US.json`
- `messages/fr-FR.json`
- `messages/ja-JP.json`
- `messages/ko-KR.json`

Retain existing `workspace.llmSettings` strings for model editor, provider management, OAuth, credential, and subscription usage behavior. New navigation strings use a Workspace settings namespace rather than Agent translation keys.

## Removal and Replacement

| Existing unit or behavior | Why it becomes obsolete | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| `/w/{handle}/settings` direct `LlmSettingsPage` rendering | `/settings` is now the settings overview authority. | `WorkspaceSettingsHubPage` | Replace the route import and rendering. | Search the route tree and confirm `/settings` imports only the Workspace settings hub. |
| Combined `LlmSettingsPage` | It composes model settings and integration management as one page. | `WorkspaceModelSettingsPage` and `LlmIntegrationsPage` | Delete after both focused Page wrappers exist. | Repository search finds no `LlmSettingsPage` symbol or import. |
| Combined `LlmSettings` component | It renders two independent tasks in one surface. | `WorkspaceModelSettings` plus `LlmIntegrations` | Delete after focused pure components and stories cover all meaningful states. | Repository search finds no `LlmSettings` component reference; Storybook uses focused components. |
| `useLlmSettingsContainer` | It couples unrelated queries, errors, modal state, and mutations. | `useWorkspaceModelSettingsContainer` and `useLlmIntegrationsContainer` | Delete after query/mutation behavior is moved. | Repository search finds no hook reference and no combined state type containing both model settings and integrations. |
| `IntegrationListState.workspaceModelSettings` coupling | Model settings do not belong to integration list state. | Separate model and integration ADTs | Replace the type definitions and all call sites. | Typecheck passes and state definitions contain only task-local data. |
| Combined `LlmSettings.stories.tsx` | Its fixture describes a surface that no longer exists. | Focused hub, model, and integration stories | Remove or replace in the same change. | Storybook test discovery contains no story for the removed combined component. |
| Duplicated layout shell logic in `AgentSettingsLayout` | Return-bar and settings-shell spacing should have one visual authority. | Shared `SettingsPageLayout`, with Agent and Workspace wrappers | Replace Agent wrapper internals without changing its public interface. | Agent settings stories/tests and typecheck pass; return bar implementation exists only in the shared primitive. |
| Workspace settings direct-page wording and route comments | They describe `/settings` as the LLM management page. | Overview and detail route documentation | Update route comments, localization, and Workspace spec. | Search for stale direct-page descriptions and old route assumptions. |
| Backend API, database state, generated public API contract | None becomes obsolete because the existing Workspace get and settings APIs remain authoritative. | Existing backend and generated client | No removal or migration. | Git diff contains no backend schema, migration, or OpenAPI contract change. |

## Test Strategy

### E2E Primary Verification Matrix

| Scenario | Actor | Verification |
| --- | --- | --- |
| Open settings overview and enter both detail pages | Workspace Owner | `/settings` shows both rows; each row reaches its stable URL; each detail returns to the overview. |
| Manage model settings after route split | Workspace Owner | Existing selectable-model values load, validation remains, and save succeeds through the existing API. |
| Manage LLM integrations after route split | Workspace Owner | Existing integrations load and the add/edit/enable/delete entry controls remain available. Destructive cleanup uses a dedicated test integration fixture. |
| Inspect settings without management permission | Workspace Member | Overview and both details load; Owner-only mutation controls are absent while current state remains visible. |
| Reject unknown settings section | Workspace member | `/settings/not-a-section` returns the product 404 surface. |
| Narrow viewport navigation | Workspace Owner | Workspace identity, return action, hub rows, and detail controls remain reachable without horizontal page overflow. |

### E2E Plan

Add a focused web E2E test under `testenv/azents/e2e/src/tests/azents/public/` using existing authenticated browser and Workspace fixture patterns. Seed one Workspace Owner, one Member, Workspace model settings, and at least one non-live provider integration. Use deterministic provider fixtures and avoid depending on external OAuth completion or provider usage endpoints.

The E2E test is the primary user-flow evidence. If local infrastructure cannot run the complete suite, run the focused test when prerequisites are available and rely on CI for the required environment. A missing required fixture or browser prerequisite is a failure for the new test, not a silent skip. Live provider/OAuth usage assertions remain outside this layout test and keep their existing optional/live policies.

### Storybook and Component Verification

Add or update static stories for:

- Workspace settings hub;
- Workspace settings header/layout at desktop and compact widths;
- model settings loading, error, loaded Owner, and loaded read-only states; and
- LLM integrations loading, error, empty Owner, loaded Owner, and loaded read-only states.

Stories use static fixtures and callbacks only. Existing OAuth and subscription usage component stories remain responsible for their detailed provider states.

### Code Quality and Build

Run from `typescript/`:

- formatting;
- azents-web lint;
- azents-web typecheck;
- azents-web build; and
- relevant Storybook tests if exposed by the workspace scripts.

Run the focused E2E test from its documented testenv environment when available. PR CI is the final required execution authority.

### Evidence Format

Record command, exit status, and any intentionally unavailable local prerequisite in the PR description or final delivery summary. CI must show all required checks passing before the goal is complete.

## Migration, Rollout, and Rollback

No database, API schema, credential, or stored-setting migration is required. The change ships as one focused frontend PR with documentation and test updates.

Rollout replaces the `/settings` page atomically with the overview and adds the two detail routes. Rollback is a normal code rollback; stored settings remain untouched because all mutations continue to use the existing APIs.

## Traceability

| Requirement | ADR decision | Design mechanism |
| --- | --- | --- |
| `workspace-260801/REQ-1` | `workspace-260801/ADR-D1` | Settings overview route and two allowlisted detail destinations |
| `workspace-260801/REQ-2` | `workspace-260801/ADR-D1`, `workspace-260801/ADR-D2` | Server-loaded Workspace identity, Workspace settings wrapper, stable return actions |
| `workspace-260801/REQ-3` | `workspace-260801/ADR-D3` | Focused containers reuse existing APIs, forms, OAuth, credential, usage, and catalog behavior |
| `workspace-260801/REQ-4` | `workspace-260801/ADR-D3` | Existing `workspaceMember.me` role derivation and backend authorization |
| `workspace-260801/REQ-5` | `workspace-260801/ADR-D2` | Shared settings layout primitive plus Workspace-specific header and responsive surfaces |
| `workspace-260801/REQ-6` | `workspace-260801/ADR-D1`, `workspace-260801/ADR-D2` | Existing WorkspaceShell/sidebar ownership remains unchanged |

## Feasibility Validation

| Item | Result | Repository evidence |
| --- | --- | --- |
| `REQ-1` overview and focused routes | Feasible | Agent settings already demonstrates a `/settings` hub plus validated `[section]` route pattern. |
| `REQ-2` Workspace identity and return navigation | Feasible | Existing public API and generated client provide Workspace lookup by handle; only a thin frontend tRPC wrapper is missing. |
| `REQ-3` preserve model and integration behavior | Feasible | `WorkspaceModelSettingsCard`, integration modal/forms/cards, OAuth components, and subscription usage are already independently reusable below the combined page. |
| `REQ-4` preserve permissions | Feasible | Existing settings container derives Owner management from `workspaceMember.me`; backend mutations remain unchanged. |
| `REQ-5` consistent responsive layout | Feasible | `AgentSettingsLayout` and `AgentSettingsHub` provide the visual baseline; the shared primitive can preserve existing Agent wrapper behavior. |
| `REQ-6` preserve unrelated navigation | Feasible | Settings remains inside the existing `(workspace)` route group and `WorkspaceShell`; no sidebar destination needs to move. |
| Removal completeness | Feasible | The combined Page, component, hook, state coupling, story, route import, and stale spec references have identifiable call sites and search-based absence checks. |
| Verification path | Feasible | Static Storybook fixtures exist for current components, browser E2E patterns exist for Agent settings, and TypeScript quality/build commands are established. |

No requirement or accepted ADR decision is blocked.

## Remaining Non-Blocking Risks

- Refactoring `AgentSettingsLayout` internals can cause subtle height or nested-scroll regression; preserve its public props and verify representative hub/detail pages.
- Workspace name lookup adds a server read per route entry; the API already exists and the payload is small.
- Model and integration containers both query the integration list; tRPC cache should avoid unnecessary refetch churn, but navigation behavior must be observed.
- Full OAuth and live subscription usage are intentionally not repeated in the layout E2E; existing specialized tests remain their authority.

## Implementation Boundary

One focused PR is sufficient because the change is frontend-owned, uses existing backend contracts, has no migration, and can be verified atomically. Implementation must include the layout refactor, Workspace settings feature, focused state owners, four locale updates, Storybook coverage, E2E coverage, living-spec updates, removal of the combined authority, and CI verification.
