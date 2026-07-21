---
title: "Backend Project Browser Manifest"
created: 2026-07-03
tags: [architecture, backend, frontend, workspace, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: backend-260703
historical_reconstruction: true
migration_source: "docs/azents/adr/0090-backend-project-browser-manifest.md"
---

# backend-260703/ADR: Backend Project Browser Manifest

## Context

[browser-260703/ADR](./browser-260703-browser-surface.md) moves the session Workspace browser toward a Project-first surface. It decides that `Projects` is the default browser mode, `All files` remains available as an explicit secondary mode, Project management moves into the Workspace panel, Project root nodes expose registry actions instead of filesystem destructive actions, empty Projects do not fall back to the Agent Workspace root, and the legacy Projects route is normalized away.

The initial design direction considered frontend synthesis of Project-root browser entries from separate Project and workspace API responses. Further design discussion changed this direction. Project manifests are needed not only after an `AgentSession` exists, but also before session creation:

- the new-session composer already has selected Project paths before `session_workspace_projects` rows exist;
- session creation uses `project_paths` as an exact bootstrap set;
- future worktree creation from another session needs to expose newly created workspace paths as reusable Project candidates before a target session exists;
- frontend-only synthesis would duplicate Project root action policy, filesystem status interpretation, and bootstrap semantics across existing-session, pre-session, and future worktree flows.

Therefore the backend should own the Project browser manifest contract and expose reusable Project-set manifest construction.

## Decision

### backend-260703/ADR-D1 — Backend owns the Project browser manifest contract

The backend constructs the Workspace browser manifest consumed by azents-web. The frontend does not synthesize Project-root browser semantics from separate Project and workspace API responses.

The backend manifest includes:

- browser modes such as `projects` and `all_files`;
- root/cwd metadata;
- Project root entries;
- entry source metadata;
- filesystem status projection;
- entry capabilities/action policy;
- empty Projects semantics;
- registration request metadata where applicable.

### backend-260703/ADR-D2 — Session Project bindings remain separate from the Agent Project catalog

Session Project bindings remain session-owned exact path bindings. They define the Project set for an existing `AgentSession` and remain the source for session prompt Project lists.

A separate Agent-scoped Project catalog stores reusable Project path candidates and their filesystem status projection. This catalog exists before a session is created and is used by new-session/bootstrap and future worktree flows.

The session binding remains path-based. It does not need to foreign-key to the Agent Project catalog in this design.

### backend-260703/ADR-D3 — Existing-session and pre-session manifest entrypoints share one entry model

The backend exposes Project browser manifest construction through two entrypoints:

- an existing-session Workspace browser endpoint that derives the Project set from `session_workspace_projects`;
- a pre-session Project manifest preview endpoint that accepts an explicit `project_paths` set before session creation.

Both entrypoints return the same Project-root browser entry model so that existing sessions, new session bootstrap, and future worktree flows consume one backend contract.

### backend-260703/ADR-D4 — Browser manifest reads never block on runtime filesystem checks

Workspace browser and pre-session manifest reads return stored DB projections. They must not call the runtime runner to stat/list Project paths before responding.

If Project filesystem status is absent, stale, or explicitly refreshed, the read path may enqueue non-blocking sync work, but the response returns the current stored projection immediately.

### backend-260703/ADR-D5 — Project filesystem status is a DB-persisted UI projection

Project filesystem status is stored in the Agent Project catalog as a UI/read-model projection of the runtime filesystem. It is not the canonical Project registry state and does not affect prompt Project list eligibility in this phase.

The first implementation does not introduce a projection generation/revision model because filesystem status is not exposed to prompt/config composition.

### backend-260703/ADR-D6 — Project filesystem status sync runs at meaningful boundaries

Project filesystem status projection is created or refreshed at boundaries where the workspace filesystem or candidate Project set likely changed, not by arbitrary read-time blocking checks.

Initial sync/update triggers are:

- Project registration success;
- Project registration request approval success;
- session creation/bootstrap with selected `project_paths`;
- directory picker path selection;
- future worktree creation success;
- run end;
- runtime runner READY transition;
- Workspace browser or pre-session manifest reads that observe stale/unchecked rows, as non-blocking enqueue only;
- user refresh, as non-blocking force enqueue.

Global periodic sync is out of scope for the first implementation.

### backend-260703/ADR-D7 — Frontend renders backend capabilities

The frontend renders entries and actions according to backend-provided capabilities. Project root destructive guardrails are backend product contract, not frontend-only inference.

For example, a Project root entry can expose `remove_project=true` while exposing filesystem `rename=false`, `move=false`, and `delete=false`. The frontend may still perform UX confirmations and handle API errors, but it does not invent Project root action policy.

## Consequences

- Project browser semantics are shared across existing-session, pre-session, and future worktree flows.
- Session creation can use a backend Project manifest preview before session rows exist.
- Runtime filesystem latency and failures do not block manifest reads.
- The Agent Project catalog becomes a persisted Project path/status read model, not merely a transient frontend preset list.
- Project filesystem status can be shown and used for UI capabilities while prompt Project list behavior remains based on registered Project paths.
- Backend API/client schemas and database schema need changes.
- Frontend implementation becomes simpler and safer because it consumes a single manifest contract.

## Alternatives

### Keep frontend-only manifest synthesis

Rejected. It duplicates Project-root semantics across existing-session, draft-session, and future worktree surfaces. It also leaves Project root safety policy in frontend inference.

### Store filesystem status only on session Project rows

Rejected. Pre-session Project selection and worktree bootstrap need Project candidates before `session_workspace_projects` rows exist. Session-scoped storage would also duplicate the same path status across sessions.

### Make Agent Project catalog the canonical logical Project identity

Rejected for this phase. The catalog is an Agent-scoped path candidate/status projection. Session Project bindings remain path-based exact sets.

### Validate Project path filesystem status synchronously in manifest reads

Rejected. It would make workspace browser and session bootstrap depend on runtime responsiveness and runner file API latency.

### Add global periodic sync first

Rejected. Meaningful boundary-driven sync is enough for the initial product path. Periodic sync can be added later if operational evidence shows that status freshness is insufficient.

### Use filesystem status for prompt Project eligibility

Rejected for this phase. The only prompt-facing Project data is the registered Project path list. Filesystem status is a UI projection and capability input only.

## Migration provenance

- Historical source filename: `0090-backend-project-browser-manifest.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
