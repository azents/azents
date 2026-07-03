---
title: "Workspace Project Browser"
created: 2026-07-03
updated: 2026-07-03
tags: [workspace, project, frontend, backend, runtime]
---

# Workspace Project Browser

## Problem and Background

Azents has three related but distinct concepts:

- organization-level Workspace, which is the collaboration and permission boundary;
- Agent Workspace, which is the runtime filesystem rooted at the provider-reported workspace path;
- session-owned Projects, which are exact path registrations under `/workspace/agent` that define an `AgentSession` working context.

The current product surface exposes the runtime file browser as an Agent Workspace root-first browser and exposes Projects through a separate session Projects tab/page. That split no longer matches the session Project model established by ADR-0076 and ADR-0086.

Users expect to browse the files relevant to the current session first. Those files are the registered Project roots, not every file under the Agent Workspace root. At the same time, new-session bootstrap already has Project paths before a session exists, and future worktree creation needs to expose newly created workspace paths as Project candidates before a target session exists.

This design defines a Project-first Workspace browser backed by a backend-owned Project browser manifest contract.

## Related Decisions

- [ADR-0076: Session-Owned Project Registry](../adr/0076-session-owned-project-registry.md)
- [ADR-0086: New Session Project Selection](../adr/0086-new-session-project-selection.md)
- [ADR-0089: Workspace Project Browser Surface](../adr/0089-workspace-project-browser-surface.md)
- [ADR-0090: Backend Project Browser Manifest](../adr/0090-backend-project-browser-manifest.md)

## Goals

- Make Projects the default Workspace browser mode for concrete sessions.
- Keep `All files` as an explicit secondary mode for root-level inspection.
- Move Project management into the Workspace surface and remove the separate Projects tab/page.
- Render Project root entries with registry-scoped capabilities and without filesystem-destructive actions.
- Preserve the absolute Agent Workspace path API contract for file operations in this phase.
- Support existing-session and pre-session Project manifest construction through one backend entry model.
- Prepare the product model for future worktree-created Project candidates.
- Keep manifest reads non-blocking with respect to runtime filesystem checks.

## Non-goals

- Do not replace session-owned Project bindings with Agent-scoped logical Project identities.
- Do not make the Agent Project catalog canonical for prompt Project eligibility.
- Do not add git clone/worktree automation in this design.
- Do not add global periodic filesystem status sync in the first implementation.
- Do not change the absolute `/workspace/agent` path-based file API contract in this phase.
- Do not delete filesystem folders when removing a Project registry row.

## Current State

Backend current state:

- `session_workspace_projects` stores `session_id` and `path` only.
- `session_workspace_project_registration_requests` stores session-scoped approval requests.
- `agent_project_presets` stores agent-scoped remembered Project paths.
- `agent_project_defaults` stores the last selected non-empty Project path set for new sessions.
- `AgentWorkspaceFileService` reads and mutates runtime files through runner operations.
- `GET /chat/v1/agents/{agent_id}/workspace` returns a root-first Agent Workspace manifest when runtime access is ready.
- Project list APIs return only session Project rows and do not include filesystem status or action policy.

Frontend current state:

- concrete session routes support `?page=projects` and render `AgentProjectsPage`.
- `AgentSessionHeader` renders Chat, Projects, and Context tabs.
- `WorkspacePanel` renders the root-first file browser and runtime settings.
- `ProjectPanel` renders session Project management as a separate page surface.
- `useAgentDraftChatContainer` builds pre-session Project selection from presets/defaults and runtime directory picker data.

## Target State

The concrete session Workspace surface contains both file browsing and Project management. `Projects` is the default browser mode. The top-level entries in this mode are the selected session's Project roots. `All files` is available as an explicit secondary mode rooted at the Agent Workspace root.

The backend owns the Project browser manifest. The frontend receives entries with status and capabilities, then renders those capabilities directly.

A Project root entry is not treated as an ordinary directory for action policy. It may expose registry actions such as `remove_project`, while disabling filesystem `rename`, `move`, and `delete` for that root. Descendant entries use ordinary filesystem capabilities.

When no Projects are registered, Project mode shows an empty state and Project registration affordances. It does not fall back to `/workspace/agent`.

Pre-session Project selection consumes the same Project browser entry model via a preview endpoint that accepts explicit `project_paths`. This lets the new-session UI and future worktree flows share semantics with existing sessions.

## Requirements

### REQ-WPB-1 — Project-first concrete session browser

Related decisions: ADR-0089-D1, ADR-0089-D5

Acceptance criteria:

- Concrete session Workspace browser opens in `Projects` mode by default.
- Top-level entries in `Projects` mode are the selected session's Project roots.
- Empty Project sets render an explicit empty Projects state.
- Empty Project sets do not render Agent Workspace root entries unless the user switches to `All files`.

### REQ-WPB-2 — Explicit All files secondary mode

Related decisions: ADR-0089-D2

Acceptance criteria:

- Users can switch to `All files` mode.
- `All files` mode is rooted at the Agent Workspace root when runtime file access is ready.
- `All files` mode is never used as an implicit fallback for empty Projects.

### REQ-WPB-3 — Project management inside Workspace surface

Related decisions: ADR-0089-D3, ADR-0089-D6

Acceptance criteria:

- Project list, registration, registration requests, approval/rejection, and Project removal are available from the Workspace surface.
- The separate Projects tab/page is removed from the normal session navigation.
- Legacy `?page=projects` URLs are normalized to the canonical session surface.

### REQ-WPB-4 — Project root capabilities are backend-provided and registry-scoped

Related decisions: ADR-0089-D4, ADR-0090-D1, ADR-0090-D7

Acceptance criteria:

- Backend manifest entries include capabilities/action policy.
- Project root entries expose registry removal when applicable.
- Project root entries do not expose filesystem delete, move, or rename capabilities.
- Frontend action menus render backend capabilities instead of inferring Project root actions locally.

### REQ-WPB-5 — Backend-owned Project browser manifest

Related decisions: ADR-0090-D1, ADR-0090-D3

Acceptance criteria:

- Existing-session Project browser manifest is served by backend API.
- Pre-session Project manifest preview is served by backend API using explicit `project_paths` input.
- Both entrypoints return the same Project browser entry model.
- Frontend does not synthesize Project-root semantics from separate Project and workspace API responses.

### REQ-WPB-6 — Agent Project catalog stores reusable status projection

Related decisions: ADR-0090-D2, ADR-0090-D5

Acceptance criteria:

- Agent-scoped Project catalog exists before a target session exists.
- Catalog rows store path candidates and filesystem status projection.
- Session Project rows remain exact path bindings and do not need a catalog foreign key.
- Prompt Project eligibility remains based on session Project bindings, not catalog filesystem status.

### REQ-WPB-7 — Manifest reads are non-blocking

Related decisions: ADR-0090-D4

Acceptance criteria:

- Manifest reads do not call runtime runner stat/list operations before responding.
- Missing, unchecked, stale, or unavailable Project statuses are represented from stored projection.
- Manifest reads may enqueue non-blocking sync work but return the current projection immediately.

### REQ-WPB-8 — Boundary-triggered Project status sync

Related decisions: ADR-0090-D6

Acceptance criteria:

- Project status sync can run after Project registration success.
- Project status sync can run after registration request approval success.
- Project status sync can run after session bootstrap with selected `project_paths`.
- Project status sync can run after directory picker selection or explicit refresh.
- Project status sync can run at run end and runtime runner READY transition.
- Future worktree creation can upsert a catalog row and request status sync without changing manifest semantics.

### REQ-WPB-9 — Preserve Agent Workspace path contract

Related decisions: ADR-0089-D2, ADR-0090-D4

Acceptance criteria:

- File read, stat, download, mkdir, move, and delete operations continue to use absolute Agent Workspace paths.
- The design does not introduce a new relative path API contract for this phase.
- Project browser entries carry enough metadata for UI rendering without replacing file operation paths.

## Decision Table

| Decision | Requirements |
| --- | --- |
| ADR-0089-D1 — Projects are the default Workspace browser mode | REQ-WPB-1 |
| ADR-0089-D2 — All files remains as a secondary inspection mode | REQ-WPB-2, REQ-WPB-9 |
| ADR-0089-D3 — Project management belongs inside the Workspace surface | REQ-WPB-3 |
| ADR-0089-D4 — Project root actions are registry-scoped, not filesystem-destructive | REQ-WPB-4 |
| ADR-0089-D5 — Empty Projects is an explicit state | REQ-WPB-1 |
| ADR-0089-D6 — Legacy Projects route is normalized away | REQ-WPB-3 |
| ADR-0090-D1 — Backend owns the Project browser manifest contract | REQ-WPB-4, REQ-WPB-5 |
| ADR-0090-D2 — Session Project bindings remain separate from the Agent Project catalog | REQ-WPB-6 |
| ADR-0090-D3 — Existing-session and pre-session manifest entrypoints share one entry model | REQ-WPB-5 |
| ADR-0090-D4 — Browser manifest reads never block on runtime filesystem checks | REQ-WPB-7, REQ-WPB-9 |
| ADR-0090-D5 — Project filesystem status is a DB-persisted UI projection | REQ-WPB-6 |
| ADR-0090-D6 — Project filesystem status sync runs at meaningful boundaries | REQ-WPB-8 |
| ADR-0090-D7 — Frontend renders backend capabilities | REQ-WPB-4 |

## User-visible Behavior

### Existing session

- Opening a concrete session shows the chat surface and Workspace panel as before, but the Workspace browser defaults to `Projects` mode.
- The Project mode root lists registered Project roots for the selected session.
- Each Project root displays a name, full path, filesystem status, and backend-provided actions.
- Removing a Project from a Project root removes only the session registry row.
- File delete/move/rename actions are not shown for Project root entries when backend capabilities disallow them.
- Users can switch to `All files` to inspect the full Agent Workspace root.
- Users can manage Projects and registration requests without opening a separate Projects tab.

### Empty Project session

- Project mode shows an empty Projects state.
- The empty state explains that no Projects are registered for the session.
- The user can register an existing directory or switch to `All files`.
- The UI does not imply that `/workspace/agent` is the session Project context.

### New session

- The draft composer continues to use explicit Project chips.
- Project preview and picker surfaces consume backend Project manifest semantics.
- Selected chip paths remain the exact `project_paths` used when creating the session.

### Legacy URL

- A URL using the old `?page=projects` query no longer renders a separate Projects page.
- The route normalizes to the canonical session surface.

## Data and State Model

### Session Project bindings

`session_workspace_projects` remains the canonical session binding table. It stores exact Project path bindings for one `AgentSession`.

The Project prompt context and session bootstrap behavior continue to use these rows. Filesystem status does not determine prompt eligibility in this phase.

### Agent Project catalog

The Agent Project catalog is an Agent-scoped read model for reusable path candidates and filesystem status projection. It exists before a target session exists.

A catalog entry stores at least:

- `agent_id`;
- `path`;
- filesystem status projection;
- last checked timestamp;
- optional status detail/error text;
- created and updated timestamps.

The catalog can be populated or refreshed by Project usage, session bootstrap, picker selection, registration approval, run-end sync, runtime READY sync, future worktree success, and explicit user refresh.

The catalog is not the canonical logical Project identity. Session rows do not need to reference it by foreign key.

### Filesystem status projection

Filesystem status is a UI projection. Initial status vocabulary should distinguish at least:

- unchecked or unknown;
- available directory;
- missing;
- unavailable because runtime/runner is not ready;
- error with detail.

The first implementation does not need projection generation/revision semantics.

## API Contract

### Existing-session manifest

A backend endpoint returns the Project browser manifest for a selected `AgentSession` and `Agent`.

Input:

- `agent_id` path parameter;
- `session_id` path parameter;
- optional browser mode or refresh intent, depending on implementation shape.

Behavior:

- validates workspace membership and session/agent match;
- derives Project set from `session_workspace_projects`;
- reads Agent Project catalog status projection for those paths;
- returns Project browser entries and capabilities;
- may enqueue non-blocking status sync when projection is missing or stale.

### Pre-session preview

A backend endpoint returns a Project browser manifest preview for explicit `project_paths` before an `AgentSession` exists.

Input:

- `agent_id` path parameter;
- body containing exact `project_paths`.

Behavior:

- validates workspace membership;
- normalizes and validates Project path policy;
- reads Agent Project catalog projection for the paths;
- returns the same Project browser entry model used by existing-session manifests;
- may enqueue non-blocking status sync for unchecked paths.

### File APIs

Existing file read/stat/download/mutation APIs continue to operate on absolute Agent Workspace paths. This design does not replace them.

## Permissions and Safety

- Existing workspace membership checks continue to apply.
- Existing session access checks continue to apply for existing-session manifests.
- Pre-session preview is Agent-scoped and requires workspace access to the Agent.
- Project removal is registry-only and must not call filesystem delete.
- Project root filesystem-destructive capabilities are disabled by backend policy.
- Frontend confirmations remain useful but are not the source of the safety contract.

## Runtime and Sync Timing

Manifest read paths must not block on runner operations.

Status sync may call runner operations only outside the manifest response path. The implementation can use best-effort non-blocking work initially, as long as the manifest contract represents unchecked/stale status explicitly and user refresh can request another sync.

Meaningful sync boundaries:

| Boundary | Reason |
| --- | --- |
| Project registration success | A session path was accepted as Project context |
| Registration request approval success | Agent-created folder became a user-approved Project |
| Session bootstrap with selected Project paths | New selected paths become reusable candidates |
| Directory picker selection | User identified a Project candidate path |
| Future worktree creation success | A new reusable path candidate exists |
| Run end | Agent may have created, deleted, or moved Project-relevant paths |
| Runtime runner READY transition | Filesystem status can be checked again |
| Browser manifest read observes stale/unchecked row | User is viewing potentially stale status |
| User refresh | User explicitly asks for updated status |

## Operational Prerequisites

- Runtime runner file stat/list operations remain available for status sync.
- API client generation is required after backend route/schema changes.
- Database migration is required for Agent Project catalog/status projection.
- Frontend tRPC router and generated client usage must stay aligned with OpenAPI.
- E2E fixtures need at least one Agent with runtime-ready workspace and deterministic Project directories.

## Rollout and Failure Modes

### Rollout

The change can roll out as a stacked series because the backend manifest can be introduced before the frontend fully switches to it. During implementation, existing APIs can remain until the frontend migration removes the old Projects page and root-first assumptions.

### Failure modes

- Catalog projection missing: manifest returns unchecked status and enqueues sync.
- Runtime not running: manifest returns stored status and capabilities that do not require live runner checks.
- Runner sync fails: catalog records unavailable/error projection; manifest remains readable.
- Project path missing: Project binding remains present; UI shows missing status and registry removal action.
- Legacy Projects route used: route normalizes to canonical session surface.

## Test Strategy

Product behavior should be verified primarily through E2E because the feature changes navigation, browser semantics, and action visibility. Backend unit tests and TypeScript type checks are required supporting gates, but they do not replace product-facing verification.

E2E primary coverage must include:

- session with multiple Projects opens Project mode by default;
- empty Project session shows explicit empty state without root fallback;
- switching to `All files` shows Agent Workspace root when runtime is ready;
- Project root action menu exposes registry removal and hides filesystem delete/move/rename;
- removing a Project deletes only the registry row and leaves files available in `All files`;
- legacy `?page=projects` normalizes away;
- new-session Project preview/picker uses backend manifest semantics;
- stale or missing status does not block manifest rendering.

Backend tests must include:

- existing-session manifest construction;
- pre-session manifest preview construction;
- catalog upsert/status projection behavior;
- non-blocking manifest read behavior with stale/unchecked projection;
- Project root capability policy;
- sync trigger service behavior at registration, approval, bootstrap, run end, and runner READY boundaries.

Frontend tests or stories should cover:

- Project mode populated state;
- Project mode empty state;
- All files mode;
- Project root capability rendering;
- Project management inside Workspace surface;
- route/header state after Projects tab removal.

Testenv fixture/prerequisite support is needed only insofar as E2E requires deterministic runtime-ready workspace contents. Fixture setup should create known directories and files under `/workspace/agent`, register selected Project paths, and keep evidence of runtime readiness. External credentials are not expected for this feature.

## Acceptance Criteria

The feature is accepted when:

- all requirements in this document are implemented;
- backend manifest APIs serve both existing-session and pre-session flows;
- manifest reads are non-blocking with respect to runtime filesystem checks;
- frontend renders Project mode by default and uses backend capabilities;
- the separate Projects tab/page is removed from normal navigation;
- `All files` remains available as explicit secondary inspection mode;
- E2E primary verification passes for populated, empty, action-policy, route-normalization, and pre-session scenarios;
- current specs are promoted to describe the implemented behavior.

## Open Questions

None that block implementation. The durable job mechanism for status sync can start as best-effort/idempotent non-blocking work if manifest reads represent unchecked/stale status explicitly and user refresh can re-request sync.

## QA Checklist

### QA-1 — Project mode is the default for existing sessions

- What to check: Opening a concrete session with registered Projects shows Project mode and Project roots first.
- Why it matters: This validates the primary product change from root-first browsing to Project-first browsing.
- How to check: Run E2E against a session with at least two registered Project paths.
- Expected result: The Workspace browser opens in Project mode and displays exactly the registered Project roots.
- Execution result: TBD
- Fixes applied: TBD

### QA-2 — Empty Projects does not fall back to Agent Workspace root

- What to check: A session with no Projects shows an explicit empty Projects state.
- Why it matters: Empty Project context must not imply full workspace context.
- How to check: Run E2E against a session created with `project_paths: []`.
- Expected result: Project mode shows empty state and registration affordances; root entries appear only after switching to `All files`.
- Execution result: TBD
- Fixes applied: TBD

### QA-3 — All files remains available as explicit secondary mode

- What to check: The user can switch from Project mode to `All files` and inspect Agent Workspace root.
- Why it matters: Debug/inspection workflows still require root-level access.
- How to check: Run E2E with runtime-ready workspace contents outside registered Project roots.
- Expected result: `All files` mode shows Agent Workspace root contents without changing Project bindings.
- Execution result: TBD
- Fixes applied: TBD

### QA-4 — Project root actions are registry-scoped

- What to check: Project root entries expose remove Project but not filesystem delete, move, or rename.
- Why it matters: Project root action safety is a backend product contract.
- How to check: Run E2E opening Project root action menus and inspect available actions.
- Expected result: Registry removal is available; filesystem destructive actions are hidden/disabled for Project roots.
- Execution result: TBD
- Fixes applied: TBD

### QA-5 — Removing a Project does not delete files

- What to check: Removing a Project registry row leaves the underlying directory available in `All files`.
- Why it matters: Project removal must remain registry-only.
- How to check: Run E2E removing a Project, then switch to `All files` and inspect the path.
- Expected result: Project disappears from Project mode, and the directory still exists in `All files`.
- Execution result: TBD
- Fixes applied: TBD

### QA-6 — Backend manifest supports pre-session preview

- What to check: New-session Project selection can preview explicit `project_paths` through backend manifest semantics.
- Why it matters: Session bootstrap and future worktree flow need Project semantics before a session exists.
- How to check: Run API/E2E flow for draft session Project chips and picker selection before first message send.
- Expected result: Preview entries use the same entry/capability/status model as existing-session Project roots.
- Execution result: TBD
- Fixes applied: TBD

### QA-7 — Manifest reads are non-blocking under stale or unavailable status

- What to check: Manifest rendering succeeds when filesystem status is unchecked/stale or runtime is not ready.
- Why it matters: Browser reads must not depend on runner responsiveness.
- How to check: Run backend test and E2E/API scenario with unchecked projection and inactive runtime.
- Expected result: Manifest returns stored/unchecked status immediately and does not fail due to missing runner access.
- Execution result: TBD
- Fixes applied: TBD

### QA-8 — Legacy Projects route is normalized away

- What to check: `?page=projects` no longer renders a separate Projects page.
- Why it matters: There must be one canonical Workspace surface.
- How to check: Run E2E navigating directly to a legacy Projects URL.
- Expected result: The route normalizes to the canonical session surface with Workspace Project management available inside it.
- Execution result: TBD
- Fixes applied: TBD

### QA-9 — Specs match implemented behavior

- What to check: Current workspace/session specs describe the implemented Project browser and manifest behavior.
- Why it matters: Specs are the source of truth after implementation.
- How to check: Run spec review against the cumulative implementation diff during spec-promotion phase.
- Expected result: Relevant specs are added/updated/removed and `last_verified_at` is current.
- Execution result: TBD
- Fixes applied: TBD
