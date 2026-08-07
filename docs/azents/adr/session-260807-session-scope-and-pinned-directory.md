---
title: "New Session Scope Selection and Pinned Directory Order Decisions"
created: 2026-08-07
tags: [session, frontend, backend, architecture]
document_role: primary
document_type: adr
snapshot_id: session-260807
---

# New Session Scope Selection and Pinned Directory Order Decisions

- Snapshot: `session-260807`
- Requirements: [session-260807/REQ](../requirements/session-260807-session-scope-and-pinned-directory.md)

## Context

The confirmed requirements add an explicit Team-or-User choice to the existing
new-session draft and change only the active Team directory ordering. Existing
Session creation already distinguishes Team and User product modes, and the active
Team directory already has a primary-session-first deterministic ordering. The
unresolved user-visible question was whether pinned rows should displace the
unmodifiable Team primary row.

## Decision Log

### session-260807/ADR-D1 — Retain Team primary before pinned active Team sessions

**Status:** Accepted on 2026-08-07.

**Requirements:** session-260807/REQ-2.

**Decision**

Order the active Team directory as Team primary first, then pinned active Team root
sessions, then unpinned active Team root sessions. Preserve the established recency
ordering and deterministic tie breakers within the pinned and unpinned groups.

**Options considered**

1. Team primary, then pinned sessions, then unpinned sessions.
2. Pinned sessions before Team primary.
3. Preserve the existing primary-and-recency order without pinned prioritization.

**Rationale**

The Team primary is the established non-pinnable canonical Team conversation and
retains its special leading position. Pinned rows still become the first discoverable
non-primary work, satisfying the requested prominence without redefining the primary
Session's role.

**Consequences**

- The active Team directory query gains pinned state as an ordering key between
  primary status and existing recency keys.
- Sidebar and archived-directory ordering remain unchanged.
- No new Session type, API contract, persistence field, or authorization path is
  introduced.
