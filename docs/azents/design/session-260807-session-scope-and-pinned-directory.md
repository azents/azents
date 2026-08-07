---
title: "New Session Scope Selection and Pinned Directory Order Design"
created: 2026-08-07
updated: 2026-08-07
implemented: 2026-08-07
tags: [session, frontend, backend]
document_role: primary
document_type: design
snapshot_id: session-260807
---

# New Session Scope Selection and Pinned Directory Order Design

- Snapshot: `session-260807`
- Requirements: [session-260807/REQ](../requirements/session-260807-session-scope-and-pinned-directory.md)
- Decisions: [session-260807/ADR](../adr/session-260807-session-scope-and-pinned-directory.md)

## 1. Current Behavior and Requirement Gap

The new-session route already resolves an optional Team-or-User scope from its URL,
and the draft container already sends the first accepted message through the matching
existing creation path. The page itself has no visible scope control, so a member
cannot choose scope in the draft experience.

The active Team directory reads a paginated Team-root projection whose ordering is
Team primary first followed by recent activity. Pin state is displayed and mutatable,
but it is not an ordering key. The directory intentionally excludes User Sessions;
their requester-owned list and access boundary remain outside this work.

## 2. Requirement and Decision Traceability

| Requirement | Design mechanisms | Decision authority |
| --- | --- | --- |
| session-260807/REQ-1 | M1 | session-260807/REQ-1 |
| session-260807/REQ-2 | M2 | session-260807/ADR-D1 |

## 3. Architecture and Ownership

### 3.1 New-session scope control

The web draft page owns the pre-send selection presentation and URL state. It
initializes from the existing route scope, defaults to Team, and updates the selected
scope before the first message. The draft container remains the single owner of the
first-message write and chooses the existing Team or User creation mutation from the
current selection.

The page header presents the two scopes as a compact, labeled segmented control next
to the existing draft controls. The same control is available in the responsive
header, so mobile users retain the selected scope and can change it without leaving
the draft. Team and User labels use the existing localized Session terminology.

Changing scope does not create, transfer, or mutate a Session. It only changes which
existing creation boundary receives a later first accepted message. Existing URL
parsing remains authoritative for direct entry, refresh, and browser navigation.

### 3.2 Active Team directory ordering

The Agent-session repository retains its current active Team-root filters and
projection joins. Its active directory query adds a pinned-state ordering key after
the Team-primary key and before the existing recency keys:

```text
Team primary first
→ pinned active Team roots
→ unpinned active Team roots
→ last user input descending
→ updated timestamp descending
→ immutable session ID ascending
```

Because the Team primary cannot be pinned, the first two groups remain disjoint.
The same repository helper supplies the directory and sidebar projections; filtering
to pinned or unpinned rows keeps their existing sidebar composition and ordering
unchanged. Archived queries remain untouched.

## 4. Security, Data, and Operations

No API schema, generated client, database migration, configuration, background job,
or runtime mode changes are required. The selector only delegates to existing
Team/User creation mutations, which retain their current authorization and
requester-owned User Session boundary. The directory continues to filter to active
Team root sessions and preserves the existing membership checks.

Pinning and unpinning retain the existing mutation and directory-query invalidation.
The refreshed active page is authoritative, so a changed row moves to the correct
group without client-side sorting or a browser reload.

## 5. Failure, Recovery, and Rollout

If a first-message creation request fails, the draft remains on screen with its
selected scope and no durable Session is created. Existing mutation error handling
remains authoritative. A directory mutation failure leaves the currently loaded rows
visible; a later successful refresh applies the server-owned order.

The change ships as one application release. It is backwards compatible with direct
new-session URLs because the existing absent-or-invalid scope resolution remains
Team. Rollback restores the previous web control and active query order without
persistent-data recovery.

## 6. Test Strategy

### E2E primary verification matrix

| Scenario | Evidence |
| --- | --- |
| Default Team draft | A member opens a new session, sees Team selected, sends the first message, and reaches a Team Session. |
| User draft selection | A member selects User before sending the first message, reaches a User Session, and that Session remains absent from Team directory results. |
| Pinned-first Team directory | A Team primary, pinned Team roots, and unpinned Team roots across multiple pages render in the required group order. |
| Pin mutation coherence | Pinning and unpinning a Team root refreshes the active directory and moves the row without a full browser reload. |
| Regression boundaries | Archived Team directory order, sidebar pinned/recent composition, and User Session authorization retain their established behavior. |

### Verification plan

Add backend repository/service coverage for the ordering keys and retain deterministic
tie-breaker assertions. Add web component stories or tests for the new scope selector
and its chosen creation path. Extend deterministic E2E coverage where the existing
authenticated browser fixture can create Team and User drafts and inspect directory
rows; otherwise retain API-level deterministic assertions for session product mode,
visibility, and page order as diagnostic evidence. CI must run the affected Python
tests, TypeScript format/lint/typecheck, generated-client drift validation if a
contract changes, and the applicable web E2E lane. A browser test failure fails the
feature whenever its fixture prerequisites are available.

## 7. Feasibility Assessment

| Requirement | Status | Evidence |
| --- | --- | --- |
| session-260807/REQ-1 | Feasible | The route already parses scope and the draft container already chooses the matching existing creation mutation. |
| session-260807/REQ-2 | Feasible | The active Team directory query already owns Team-primary and recency ordering, pin state, pagination, and deterministic session-ID tie breaking. |

No requirement blocker was found.

## 8. Alternatives and Non-Blocking Risks

Making Pinned the first group was rejected by session-260807/ADR-D1 because it would
displace the established canonical Team primary Session. Adding a new User Session
directory was excluded because it changes the confirmed Team-directory boundary and
is not required to choose User at creation time.

Offset pages can shift after a pin mutation. Existing invalidation and the
server-owned deterministic ordering provide the intended recovery without a new
snapshot mechanism.

## 9. Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Draft-page Team/User selector delegates first-message creation through the existing selected scope and retains Team as the default | session-260807/REQ-1 | required |
| M2 | Active Team directory orders Team primary, pinned roots, then unpinned roots before existing deterministic recency keys | session-260807/REQ-2, session-260807/ADR-D1 | decided |

## 10. Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Implicit-only new-session scope choice | session-260807/REQ-1 | Explicit draft-page Team/User choice | Draft header controls | A member can select either scope before the first message. |
| Active Team directory's primary-then-recency-only ordering | session-260807/REQ-2, session-260807/ADR-D1 | Primary-then-pinned-then-recency ordering | Active Team repository query and order assertions | No active-directory ordering path omits the pinned priority key. |
| API contracts, persistence, User Session ownership, sidebar composition, and archived ordering | None; retained | Existing sources remain authoritative | Not applicable | No generated-client, migration, ownership, sidebar, or archived-query change is introduced. |

## 11. Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-08-07`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2`
- Approved scope: explicit new-session Team/User choice with Team default, and
  primary-then-pinned active Team directory ordering.
