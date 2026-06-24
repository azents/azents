---
title: "ADR-0005: Add Session Sandbox Workspace Browser API"
created: 2026-05-01
tags: [architecture, backend, frontend, api]
---

# ADR-0005: Add Session Sandbox Workspace Browser API

## Context

The NoIntern web chat screen had an existing file exploration UX based on `session-data`, but that feature was not a browser for the `/home/sandbox` runtime filesystem. What users expect is to browse the actual `/home/sandbox` root that the session sandbox sees, then read and download files created by the agent directly from the Web UI.

Problems in the existing structure:

- `session-data` is an upload/attachment store and is not the source of truth for the sandbox working directory.
- The existing `SessionExplorer` is an auxiliary modal UX, making it hard to evolve into a workspace panel next to the chat screen.
- If sandbox lifecycle becomes visible lazily only through shell tool calls, users cannot easily understand why the browser is empty.

## Decision

Do not extend the existing `session-data` browser. Build the new workspace browser as a separate Workspace API and frontend feature slice targeting the session sandbox's `/home/sandbox`.

Key decisions:

1. Remove the existing `SessionExplorer`-based session data browser UX during preparation.
2. Define a new public API at `/chat/v1/sessions/{session_id}/workspace...` instead of reusing `session-data`.
3. Show file contents only when the sandbox is active.
4. When the sandbox is inactive, show a `Start sandbox` CTA in the browser area. The CTA calls an explicit start/resume API.
5. MVP is read-only and includes only list/read/download/preview. Write/delete/edit/concurrency are deferred to later phases.

## Considered Options

### A. Extend the existing `session-data` browser

Reasons rejected:

- `session-data` and `/home/sandbox` have different ownership, lifecycle, and security boundaries.
- Mixing upload attachment paths and sandbox runtime paths in the same API would make future edit/download policy unclear.
- Keeping the existing modal UX makes it hard to address the core issue: moving to an agent-centric workspace panel.

### B. Add a new Workspace API and new frontend feature slice, which is this decision

Reasons accepted:

- The API contract directly represents root `/home/sandbox`, sandbox active/inactive state, and read-only capabilities.
- The existing session data upload/download features can remain while only the browser UX is replaced independently.
- Future Git diff, editing, and live sync capabilities can expand phase by phase within the same Workspace domain.

### C. Proxy sandbox-daemon API directly to Web

Reasons rejected:

- Session access control and workspace membership validation would bypass the public API layer.
- Path confinement, MIME/preview policy, and download header policy would be spread into a Web proxy.
- It would be difficult to integrate sandbox lifecycle start/resume and manifest contracts in the service layer.

## Consequences

### Positive

- The workspace browser's source of truth becomes the sandbox runtime.
- Inactive sandbox UX is explicit, so users do not mistake an empty browser for an error.
- The read-only MVP reduces scope, allowing the backend API, frontend panel, and preview shell to ship safely first.

### Negative

- This is a cross-cutting change touching public API, service layer, generated client, tRPC, and frontend layout.
- The UI must handle inactive state and start/resume state because workspace lifecycle changes when the user sends the first message or explicitly clicks `Start sandbox`.
- Existing `session-data` endpoints may remain for attachments for a while, creating naming confusion. The workspace browser design does not reuse them.

## References

- GitHub Discussion: https://github.com/azents/azents/discussions/3202
- Design document: [`../design/enhanced-file-browser.md`](../design/enhanced-file-browser.md)

## Status

**Accepted** (2026-05-01). Discussion #3202 agreed on dropping the old browser, showing the browser only for active sandboxes, shipping a read-only MVP, and deferring Git/editing work.
