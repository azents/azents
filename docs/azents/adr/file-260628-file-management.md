---
title: "Add Agent Workspace File Management Operations"
created: 2026-06-28
tags: [backend, frontend, api, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: file-260628
historical_reconstruction: true
migration_source: "docs/azents/adr/0082-agent-workspace-file-management.md"
---

# file-260628/ADR: Add Agent Workspace File Management Operations

## Context

The Agent Workspace panel currently provides a read-only browser for the Runtime Provider-reported Agent Workspace root. Users can inspect directories, preview files, and download files, but cannot perform basic filesystem organization tasks from the UI.

The MVP scope is limited to Agent Workspace files only:

- delete
- rename
- mkdir
- move
- inspector for basic file/directory metadata

The scope explicitly excludes ExchangeFile attachments, Artifacts, ModelFile/FilePart, upload, and file content editing.

The current Runtime Runner protocol has native operations for `file.stat`, `file.list`, `file.read`, `file.write`, and `file.grep`. A lower-level `RuntimeRunnerFileStorage.delete()` helper exists, but it shells out to `rm -rf`. That helper is intended for internal tool storage and does not provide a precise user-facing contract for destructive workspace operations.

## Decision

### file-260628/ADR-D1 — Use native Runner file management operations

Add native Runtime Runner operations for Agent Workspace file management:

- `file.delete`
- `file.mkdir`
- `file.move`

Do not implement the public Agent Workspace MVP by shelling out to `rm`, `mkdir`, or `mv` from the server.

### file-260628/ADR-D2 — Keep root confinement in the Agent Workspace service layer

The user-facing Agent Workspace API must normalize every source and destination path against the Provider-reported `agent_runtimes.workspace_path`. A path equal to the Agent Workspace root is allowed for stat/list but forbidden for destructive delete and move source operations.

Runner operations may continue to accept absolute Runtime paths because non-user-facing tools need that flexibility. The public API boundary owns Agent Workspace confinement.

### file-260628/ADR-D3 — Model rename as move

Do not add a separate backend or Runner `rename` operation. Rename is a `file.move` where source and destination share the same parent directory. The frontend may expose Rename as a distinct action, but the API and Runner contract use move.

### file-260628/ADR-D4 — Expose inspector through stat metadata

Add a stat-focused Agent Workspace API response for inspector UI. Inspector reads metadata through `file.stat`, not through file content preview. Basic metadata includes path, name, kind, size, media type, modified time, symlink flag, real path, and resolved kind when available.

### file-260628/ADR-D5 — Use conservative destructive defaults

Directory delete requires an explicit `recursive=true` request. Move overwrite defaults to false and fails on existing destination unless explicitly enabled by the request contract. The MVP UI should default to non-overwriting moves and require explicit confirmation for delete.

## Consequences

### Positive

- File management semantics are explicit and testable in the Runtime protocol.
- Public API policy remains separate from Runner filesystem mechanics.
- Rename and move share one backend path, reducing duplicate behavior.
- Inspector can be fetched cheaply without reading file contents.
- Destructive operations have clear guardrails for root deletion and recursive directory deletion.

### Negative

- The protocol, generated protobuf code, Runner implementation, server operation client, public API, generated OpenAPI clients, tRPC router, and UI all change in one cross-cutting feature.
- Native operations require more implementation and test coverage than a shell shortcut.
- Existing provider deployments must roll out a Runner image that advertises and supports the new file operation capabilities.

## Alternatives

### A. Use shell commands from server-side file storage helpers

Rejected. It is faster to implement, but the resulting public contract depends on shell stderr, always risks overly broad recursive deletion, and makes auditability poor.

### B. Add separate rename operation

Rejected. Filesystem rename is move within the same parent directory. A separate operation would duplicate destination validation, overwrite policy, and error mapping.

### C. Extend file preview response for inspector

Rejected for MVP. Preview reads content and can hit preview byte limits or binary decoding paths. Inspector needs metadata only, so `file.stat` is the correct source.

## Migration provenance

- Historical source filename: `0082-agent-workspace-file-management.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
