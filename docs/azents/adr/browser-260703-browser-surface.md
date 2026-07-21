---
title: "Workspace Project Browser Surface"
created: 2026-07-03
tags: [architecture, frontend, workspace, product, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: browser-260703
historical_reconstruction: true
migration_source: "docs/azents/adr/0089-workspace-project-browser-surface.md"
---

# browser-260703/ADR: Workspace Project Browser Surface

## Context

Azents already distinguishes organization-level Workspace from the Agent Workspace filesystem reported by the runtime provider. Agent Workspace file management exists as a runtime-backed browser rooted at the provider-reported Agent Workspace path, while session-owned Projects exist as exact path registrations under `/workspace/agent`.

[registry-260625/ADR](./registry-260625-registry.md) made Project registrations session-owned. [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-58) made new-session Project selection explicit: the selected Project chips are the exact `project_paths` used to create the new `AgentSession`, and session creation no longer copies hidden Projects from the team-primary session.

The current user interface still exposes Projects as a separate session tab/page and exposes the runtime file browser as an Agent Workspace root-first surface. That creates product and safety issues:

- users work from Projects, but the browser starts at the Agent Workspace root;
- Project management is split from the file browser even though both describe the same runtime workspace;
- Project root nodes need registry-level actions, while ordinary filesystem nodes need file actions;
- an empty Project set must be explicit instead of silently falling back to the Agent Workspace root;
- legacy `?page=projects` routing keeps a Projects page as a peer surface after Project management has moved into Workspace.

## Decision

### browser-260703/ADR-D1 — Projects are the default Workspace browser mode

The Workspace browser defaults to a Project-oriented mode. In this mode, the top-level browser entries are the selected session's registered Project roots.

Users should enter the filesystem through the Project set that defines the current session's working context, not through the Agent Workspace root.

### browser-260703/ADR-D2 — All files remains as a secondary inspection mode

The Workspace browser keeps an explicit `All files` mode rooted at the Agent Workspace root.

`All files` is a secondary inspection/debug mode for users who need to inspect workspace contents outside the registered Project set. It is not the default mode and must not be used as an implicit fallback when Projects are empty.

### browser-260703/ADR-D3 — Project management belongs inside the Workspace surface

Project list, registration, registration requests, and Project removal move into the Workspace panel/surface. A separate Projects tab/page is removed as a primary navigation destination.

Project management is still session-scoped: removing a Project removes only the session registry row and does not delete files.

### browser-260703/ADR-D4 — Project root actions are registry-scoped, not filesystem-destructive

A Project root browser entry exposes Project registry actions such as removing the Project from the session. It does not expose destructive filesystem actions such as delete, move, or rename as Project-root actions.

Filesystem actions remain available for ordinary filesystem entries according to the backend-provided action policy.

### browser-260703/ADR-D5 — Empty Projects is an explicit state

When a session has no registered Projects, Project browser mode shows an empty Projects state with Project registration affordances. It must not fall back to the Agent Workspace root.

Users can switch to `All files` explicitly if they need root-level inspection.

### browser-260703/ADR-D6 — Legacy Projects route is normalized away

Legacy session URLs that request the old Projects page, such as `?page=projects`, are normalized to the canonical session Workspace/Chat surface. The Projects page is not kept as an independent long-term route.

## Consequences

- The browser's default mental model matches session-owned Projects.
- Project management and file inspection share one operational surface.
- Empty sessions remain honest: no Project context is implied by the Agent Workspace root.
- Project root destructive guardrails become a product contract rather than a UI accident.
- Existing frontend route and header tab logic must change.
- Existing file browser components can be reused, but they must render backend-provided entry capabilities rather than inferring actions only from file kind.

## Alternatives

### Keep Projects as a separate tab/page

Rejected. It keeps Project management split from the filesystem browser and makes users switch contexts to understand which folders define the session working set.

### Default to Agent Workspace root and visually highlight Projects

Rejected. It preserves the current root-first mental model and makes empty Project sessions look like full-workspace sessions.

### Treat Project root entries like ordinary directories

Rejected. Project root entries represent both a filesystem path and a session registry binding. Deleting, moving, or renaming a Project root from the Project browser would be ambiguous and unsafe.

### Remove All files entirely

Rejected. Root-level inspection remains useful for debugging, recovery, and understanding runtime-created files outside Projects. Keeping it as an explicit secondary mode preserves that capability without making it the default.

## Migration provenance

- Historical source filename: `0089-workspace-project-browser-surface.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
