---
title: "ADR-0086: New Session Project Selection"
created: 2026-06-29
tags: [architecture, product, backend, frontend]
---

# ADR-0086: New Session Project Selection

## Context

Azents currently has session-owned Project registrations. A Project registration is a runtime workspace path associated with an `AgentSession`. New team sessions historically received a snapshot copy of the team-primary session's Projects.

That copy behavior was useful as a bootstrap shortcut, but it is not the intended product model for explicit multi-session work:

- users should be able to decide which Projects a new session uses before sending the first message;
- the Project chips shown in the new-session UI should exactly match the Project registrations that the created session receives;
- the team-primary session should not act as the hidden source of truth for new session Projects;
- nested directories and parent/child Project paths are valid user-selected working scopes;
- Project presets are needed for convenience, but should not become a logical Project/source/materialization model in this phase.

This ADR refines ADR-0074 and ADR-0076 for the first explicit Project-selection step. It does not decide git clone, worktree, Project source, Project trust, or Project-local config behavior.

## Decision

### ADR-0086-D1 — New-session Project chips are the exact Project set

The Project chip list on the new session page is the exact set of Project paths that the created session receives.

`project_paths: []` creates a session without Project registrations. `project_paths: ["/workspace/agent/a", "/workspace/agent/b"]` creates a session with exactly those two Project registrations.

No hidden team-primary Project copy is applied when creating a new session through the explicit Project-selection API contract.

### ADR-0086-D2 — Session creation APIs require `project_paths`

Team session creation APIs must require `project_paths` and interpret it as an exact set.

This applies to both first-message session creation and direct session creation:

- `POST /chat/v1/agents/{agent_id}/sessions/messages`
- `POST /chat/v1/agents/{agent_id}/sessions`

The absence of `project_paths` is invalid for these APIs after this change. This is an intentional public API contract change for the new Project-selection model.

### ADR-0086-D3 — New-session defaults come from the latest non-primary session

The new session page initializes its selected Project chips from the latest active non-primary session for the Agent, ordered by session `created_at` descending.

If no active non-primary session exists, the default selected Project list is empty.

The team-primary session is not used as a fallback for default selection.

### ADR-0086-D4 — Agent-owned Project Catalog is a preset store only

Azents will introduce an Agent-owned Project Catalog for this phase, but it is only a Project path preset store.

The minimal catalog stores:

- Agent ID
- Project path
- timestamps

It does not store or imply:

- display name
- source kind
- git metadata
- archived state
- default state
- materialization state
- trust or permission state
- logical Project identity beyond a remembered path preset

### ADR-0086-D5 — Catalog is populated by Project usage

Whenever a session is created with `project_paths`, each path is upserted into the Agent-owned Project Catalog.

Whenever an existing session registers a Project path, that path is also upserted into the Agent-owned Project Catalog.

The catalog list is sorted by most recently upserted/updated paths first.

Existing data is migrated by deduplicating historical `session_workspace_projects` through `agent_sessions.agent_id` and path.

### ADR-0086-D6 — Session Project rows remain path-only bindings

`session_workspace_projects` remain session-owned path bindings. They do not reference the Agent-owned Project Catalog by foreign key in this phase.

The catalog is a preset source, not the canonical Project identity for a session binding.

### ADR-0086-D7 — Nested and overlapping Project paths are allowed

Project paths may be nested under `/workspace/agent`, and a session may register parent and child Project paths at the same time.

Examples that are valid in the same session:

```text
/workspace/agent/azents
/workspace/agent/azents/packages/api
```

Exact duplicate paths in one session are still not meaningful. The session creation path should deduplicate repeated exact paths before creating rows.

`/workspace/agent` itself remains invalid as a Project path.

### ADR-0086-D8 — Direct selection uses a dedicated directory picker

The new session page's direct Project selection flow uses a dedicated directory picker modal, not the existing workspace management panel.

The picker:

- requires runtime/runner file access;
- shows a runtime start CTA when the runtime is inactive;
- shows loading/recovery states during runtime transitions;
- allows selecting directories under `/workspace/agent`, including nested directories;
- disallows selecting `/workspace/agent` itself;
- disallows selecting files;
- does not expose file-management actions such as delete, move, rename, mkdir, or download.

### ADR-0086-D9 — Session creation performs registry-level path validation only

Session creation validates Project paths as registry input but does not perform runner filesystem existence checks.

Required validation:

- path is absolute;
- path is under `/workspace/agent`;
- path is not `/workspace/agent` itself;
- exact duplicates are deduplicated.

This keeps session creation independent of runtime readiness and allows stale presets to be selected. Existing explicit Project registration for a running session may keep stronger runtime directory existence validation.

## Consequences

- New session creation becomes explicit and predictable: the UI chip set equals the created session Project set.
- Team-primary session Projects no longer implicitly bootstrap new sessions through the new API contract.
- A minimal Agent-owned Project Catalog provides dropdown presets without committing to a full Project source/modeling system.
- Nested Project paths become supported, so Project-scoped instruction loading must handle overlapping path scopes deliberately.
- Session creation no longer depends on runner readiness for Project path presets.
- Existing tests and public client types for session creation must be updated because `project_paths` becomes required.
- Future worktree, git metadata, source, trust, and Project-local config decisions remain deferred.

## Alternatives

### Continue copying team-primary Projects

Rejected. It keeps the Project source of truth hidden in the team-primary session and makes the new session UI misleading.

### Make `project_paths` optional and preserve legacy copy on omission

Rejected. It preserves compatibility but keeps two meanings for session creation and delays cleanup of the old bootstrap behavior.

### Use previous session rows directly as dropdown presets

Rejected. A minimal Agent-owned catalog/preset table is simpler for the API and creates a clear extension point while still remaining intentionally lightweight.

### Make the catalog the canonical Project model and link session rows by FK

Rejected for this phase. The catalog is a preset store only. Logical Project identity, source metadata, git metadata, and materialization are intentionally out of scope.

### Restrict Projects to direct children of `/workspace/agent`

Rejected. Nested directories are valid Project working scopes, especially for monorepos and mixed project layouts.

### Reject parent/child Project overlap

Rejected. Users may intentionally select both a broader repository and a nested sub-area as Projects in the same session.

### Validate preset paths against the runner during session creation

Rejected. It would make first-message session creation depend on runtime readiness and would turn stale presets into chat-start failures.
