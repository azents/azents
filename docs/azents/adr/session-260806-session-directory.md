---
title: "Session Directory Decisions"
created: 2026-08-06
tags: [session, api, frontend, architecture]
document_role: primary
document_type: adr
snapshot_id: session-260806
---

# Session Directory Decisions

- Snapshot: `session-260806`
- Requirements: [session-260806/REQ](../requirements/session-260806-session-directory.md)

## Context

The confirmed requirements establish two different read models for root sessions of one Agent: a complete active-or-archived directory that must support pagination, and a compact sidebar that must show all pinned active sessions plus at most 20 recent active sessions without archived data. The current active and archived list routes each return every matching root session and are consumed by the Agent-focused shell.

## Decision Log

### session-260806/ADR-D1 — Separate session directory and sidebar-summary read contracts

**Status:** Accepted on 2026-08-06.

**Requirements:** session-260806/REQ-1, session-260806/REQ-2, session-260806/REQ-3, session-260806/REQ-4.

**Decision**

Provide separate read contracts for the complete session directory and the compact Agent sidebar. The directory contract returns one paginated active or archived root-session list. The sidebar-summary contract returns all eligible pinned active root sessions and at most 20 distinct recent active root sessions, and returns no archived sessions.

**Options considered**

1. Separate directory and sidebar-summary contracts.
2. One generic list contract composed through multiple client requests and client-side deduplication.
3. A list contract with UI-specific directory and sidebar modes.

**Rationale**

The two surfaces have different boundedness, ordering, and composition requirements. A dedicated sidebar summary keeps pin/recent deduplication authoritative and avoids loading archived or complete active-session data merely to render navigation. A directory-specific contract preserves a clear pagination boundary.

**Consequences**

- Directory and sidebar queries are invalidated together after mutations that can alter either projection.
- Existing unbounded active and archived list contracts are replaced at their current consumers rather than retained as compatibility fallbacks.
- The next decision defines the directory pagination and addressability contract.

### session-260806/ADR-D2 — Offset pagination with page-addressable directory state

**Status:** Accepted on 2026-08-06.

**Requirements:** session-260806/REQ-1, session-260806/REQ-2, session-260806/REQ-4.

**Decision**

The directory uses offset-and-limit pagination. Its response includes `items`, `total_count`, `offset`, and `limit`. The web directory exposes the selected active-or-archived status and one-based page number in its URL query state.

**Options considered**

1. Offset pagination with total count and page-addressable URL state.
2. Cursor pagination with next/previous navigation.

**Rationale**

The required directory is a conventional page-navigation surface. Offset pagination allows direct page selection, visible page counts, browser history, and shareable status/page URLs without translating opaque cursors at the UI boundary.

**Consequences**

- The directory query uses a bounded page size and translates its one-based URL page number to a zero-based API offset.
- Mutations can move rows between or within pages; affected directory queries and the sidebar summary refresh after a successful mutation.
- Repositories add deterministic final tie breakers to existing user-visible ordering so equal timestamps do not produce unstable pages.
