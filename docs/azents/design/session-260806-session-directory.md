---
title: "Session Directory Design"
created: 2026-08-06
updated: 2026-08-06
implemented: 2026-08-06
tags: [session, api, frontend, backend]
document_role: primary
document_type: design
snapshot_id: session-260806
---

# Session Directory Design

- Snapshot: `session-260806`
- Requirements: [session-260806/REQ](../requirements/session-260806-session-directory.md)
- Decisions: [session-260806/ADR](../adr/session-260806-session-directory.md)

## 1. Current Behavior and Requirement Gap

`GET /chat/v1/agents/{agent_id}/sessions` returns every active root session, including unread-run and automatic-archive projections. `GET /chat/v1/agents/{agent_id}/sessions/archived` returns every archived root session. `AgentFocusedShell` loads both unbounded responses and passes them to `AgentFocusedSidebar`, where active and archived sessions are both rendered.

This violates the bounded-navigation goal and provides no page-addressable complete directory. The existing repository already owns root-session filtering, active and archived ordering, unread-run projection, automatic-archive deadline projection, membership validation, and Team primary-session ensuring for active lists. Those behaviors remain the source of truth.

## 2. Requirement and Decision Traceability

| Requirement | Design mechanisms | Decision authority |
| --- | --- | --- |
| session-260806/REQ-1 | M1, M2, M3 | session-260806/ADR-D1, session-260806/ADR-D2 |
| session-260806/REQ-2 | M1, M2, M3, M6 | session-260806/ADR-D1, session-260806/ADR-D2 |
| session-260806/REQ-3 | M1, M4 | session-260806/ADR-D1 |
| session-260806/REQ-4 | M5, M6 | session-260806/ADR-D1, session-260806/ADR-D2 |

## 3. Architecture and Ownership

### 3.1 Read-model boundaries

The backend owns both session-list projections:

- **Directory page projection**: one status-selected page of root sessions, a total count, and pagination metadata.
- **Sidebar summary projection**: all eligible pinned active root sessions plus at most 20 distinct recent active root sessions; it never includes archived sessions.

The web client owns URL parsing, one-based page presentation, and query invalidation after mutation. It does not compose pinned and recent rows from broad raw lists or deduplicate them client-side.

`AgentSession` remains the source of truth for session identity, status, primary role, pin state, title, activity timestamps, and archive metadata. Existing unread-run and automatic-archive projections remain owned by the Agent-session repository/service paths.

### 3.2 API contract replacement

Replace the current unbounded active and archived list contracts at their current consumers with:

```text
GET /chat/v1/agents/{agent_id}/sessions
  ?status=active|archived
  &offset=<non-negative integer>
  &limit=<1..bounded maximum>

GET /chat/v1/agents/{agent_id}/sessions/sidebar
```

The directory endpoint returns a page response containing:

```text
items: AgentSessionResponse[]
total_count: integer
offset: integer
limit: integer
current_archive_retention_days: integer | null
```

The sidebar endpoint returns:

```text
pinned: AgentSessionResponse[]
recent: AgentSessionResponse[]
```

`pinned` contains active root sessions with `pinned = true`. `recent` contains at most 20 active root sessions with `pinned = false`. The Team primary session participates in the recent projection because it is an active root session and cannot be pinned. The two arrays are disjoint by contract.

The endpoint validates Agent existence and Workspace membership before returning either projection. Active directory and sidebar reads retain the existing Team primary-session ensure behavior. Archived directory reads do not create a Team primary session merely to display archived history.

### 3.3 Repository and service mechanics

The Agent-session repository gains bounded, status-specific directory queries and a sidebar-summary query. Each directory query performs a matching count and page select with the same root-session and status predicates.

Ordering retains the current product behavior:

- Active: Team primary first; then descending `last_user_input_at`; then descending `updated_at`.
- Archived: descending `archived_at`; then descending `updated_at`.

Each order adds the immutable session ID as its final tie breaker to make page boundaries deterministic when timestamps are equal.

The active directory page keeps the existing unread terminal-run and automatic-archive deadline projection. Archived rows retain their archive-retention snapshot and purge deadline. The sidebar summary uses the same active-row projection so its indicators and pin behavior remain consistent with the directory.

The service exposes distinct methods for the directory and sidebar projections, retaining existing membership checks and primary-session creation behavior at the service boundary. The API route translates its status query to the correct service method and rejects invalid pagination parameters through explicit query validation.

No schema migration is required: all selection, ordering, pin, status, retention, and projection inputs already exist in `agent_sessions` and related unread-run/session-agent tables.

## 4. Web Experience

### 4.1 Directory route and URL state

Add the Agent-scoped route:

```text
/w/{handle}/agents/{agentId}/sessions
```

The route renders a dedicated session directory inside the existing Agent-focused shell. It uses query state:

```text
?status=active&page=1
?status=archived&page=3
```

Missing or invalid query values resolve to `status=active` and `page=1`. The client translates the one-based page to `offset = (page - 1) * pageSize`; `pageSize` is a local implementation constant selected as 25 for the initial release. A status switch resets the page to 1. Page controls render only usable pages, include previous/next behavior, and replace query state without losing the Agent route.

When a refresh leaves the selected page beyond the last available page, the client navigates to the last valid page and refetches. An empty first page presents the empty state for the selected status.

### 4.2 Directory contents and actions

The directory provides Active and Archived controls, a status-aware empty state, the paginated rows, and the page controls. Rows retain current session presentation: title, timestamp, Team primary state, run state, unread terminal-run indicator, pin indicator, automatic-archive information where applicable, and archived retention/deletion information where applicable.

- Active rows link to the existing direct session route and retain rename, pin/unpin, and permitted archive actions.
- Archived rows link to the existing direct session route and retain the existing permitted restore action and retention presentation.
- Existing primary-session, running-session, authorization, and read-only restrictions are not reimplemented in the client; route errors remain authoritative.

### 4.3 Sidebar

`AgentFocusedShell` fetches only the sidebar summary on its five-second refresh interval. It no longer requests archived sessions.

`AgentFocusedSidebar` renders:

1. a pinned group when it has pinned rows;
2. a recent group containing at most 20 non-pinned active rows; and
3. a visible "All sessions" route to the directory.

The archived expandable section, its loading/error states, restore callback, and archived query wiring are removed. Existing create, rename, pin/unpin, archive, navigation, and account controls remain. The sidebar does not own directory pagination state.

### 4.4 Mutation coherence

Title update, pin update, archive, restore, session creation, session activity updates, and session-read acknowledgment invalidate the sidebar summary and affected directory queries. Existing selected-session detail invalidation remains.

After archive or restore succeeds, the initiating directory refreshes both status pages and preserves the current URL when still valid; the page-clamping rule handles a now-empty out-of-range page. When archive succeeds from the sidebar while it targets the open session, existing navigation to the new-session route remains.

## 5. Security, Data, and Operations

The new read endpoints inherit current Agent existence and Workspace-membership checks. They expose no new session fields and preserve root-only visibility, so subagent sessions remain excluded. The client continues to use existing authenticated tRPC/API-client transport.

Offset pagination may shift rows when a concurrent session mutation changes ordering. The next query is authoritative, and mutation-driven invalidation plus deterministic ordering prevents duplicated equal-timestamp rows within one response. Exact snapshot isolation across independent page requests is not introduced because it is neither required nor provided by the current list contract.

The directory requires one bounded count query and one bounded row query per load. The sidebar requires bounded recent-row retrieval plus its pinned projection. No background jobs, configuration, cache, migration, or runtime-mode changes are introduced. API OpenAPI output and generated Python/TypeScript public clients must be regenerated from the changed route contract.

## 6. Failure, Recovery, and Rollout

A directory or sidebar query failure displays the existing localized load-error treatment without hiding the rest of the Agent shell. A mutation failure preserves the last rendered data and shows the existing action error surface; the next scheduled sidebar refresh or manual directory retry may recover presentation.

The change is released atomically with backend route/schema changes, regenerated clients, and web consumers. There is no compatibility fallback to the unbounded list response: existing current consumers move to the new contracts in the same change. Rollback restores the prior application version and its matching generated client artifacts; persistent data is unchanged.

## 7. Observability

Existing request logging and route error handling cover the new endpoints. Verification focuses on response bounds, exclusion predicates, page metadata, membership protection, and client query invalidation. No new telemetry authority or data collection is required.

## 8. Test Strategy

### E2E primary verification matrix

| Scenario | Evidence |
| --- | --- |
| Active directory pagination | A member opens page 1 and a later page, sees only active root sessions in established order, and opens a session from each page. |
| Archived directory pagination | A member switches to archived status, navigates pages, sees retention information, and restores a listed session. |
| Sidebar bound | An Agent with more than 20 non-pinned active root sessions and multiple pinned sessions shows every pinned row, at most 20 distinct recent rows, no archived group, and an All sessions link. |
| Mutation coherence | Pin, archive, restore, and title actions refresh the directory and sidebar without a browser reload. |
| Authorization and visibility | A non-member cannot read either projection, and subagent sessions do not appear in either directory status or the sidebar. |

### E2E plan and prerequisites

Extend the deterministic public-chat E2E fixture support to create an Agent with enough active, pinned, archived, and subagent sessions to cross at least two directory pages. Execute browser-level E2E coverage where the existing test environment supports authenticated web navigation; use deterministic API E2E coverage for setup and contract assertions when browser execution is unavailable. Test evidence records URLs, status/page controls, visible row identifiers, and response/page metadata.

### Unit and integration coverage

- Repository tests cover active and archived page predicates, counts, order tie breakers, offsets, sidebar pinned/recent disjointness, root-only filtering, and the 20-row recent bound.
- Service/API tests cover authorization, Team primary ensure behavior, response serialization, validation, and archive metadata.
- Web component/container tests cover URL parsing, status/page transitions, empty/out-of-range recovery, sidebar archived removal, and mutation invalidations.
- Generated-client type checks verify route-contract consumers after regeneration.

### CI policy

Run backend targeted tests, TypeScript format/lint/typecheck, generated-client validation, and deterministic E2E tests in CI. Browser E2E failures fail the feature when browser prerequisites are available. If an environment prerequisite prevents browser execution, record the blocker and retain API-level deterministic evidence; this does not waive the planned browser scenario.

## 9. Feasibility Assessment

| Requirement | Status | Evidence |
| --- | --- | --- |
| session-260806/REQ-1 | Feasible | Existing root active query, Agent shell, direct session route, tRPC layer, and offset-list patterns are present. |
| session-260806/REQ-2 | Feasible | Existing archived root query, retention projection, restore route, and archived UI behavior are present. |
| session-260806/REQ-3 | Feasible | Current sidebar owns the relevant navigation/actions; backend already stores pin and activity fields needed for a summary query. |
| session-260806/REQ-4 | Feasible | Current mutations already use tRPC invalidation; directory/sidebar query keys can be invalidated together. |

No requirement blocker was found. The only material API choices were accepted in ADR-D1 and ADR-D2.

## 10. Alternatives and Non-Blocking Risks

A client-composed generic list was rejected by ADR-D1 because it broadens sidebar loads and duplicates server-owned selection logic. Cursor pagination was rejected by ADR-D2 because it does not directly support page-addressable navigation.

Offset pages can move while a user views a mutable list. Deterministic ordering, refresh after successful mutations, and out-of-range page clamping provide bounded, understandable recovery. Search and arbitrary sorting remain out of scope and may require a new snapshot if introduced later.

## 11. Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Separate directory-page and sidebar-summary session read contracts | session-260806/ADR-D1 | decided |
| M2 | Offset page metadata and page-addressable directory URL state | session-260806/ADR-D2 | decided |
| M3 | Agent-scoped active/archived directory route and status-separated page experience | session-260806/REQ-1, session-260806/REQ-2, session-260806/ADR-D1, session-260806/ADR-D2 | derived |
| M4 | Sidebar renders only server-composed pinned and bounded recent active projections, with no archived query or section | session-260806/REQ-3, session-260806/ADR-D1 | derived |
| M5 | Shared invalidation and out-of-range-page recovery after session mutations | session-260806/REQ-4, session-260806/ADR-D1, session-260806/ADR-D2 | derived |
| M6 | Retain current authorization, root-only visibility, pin/archive semantics, retention metadata, and direct session navigation | session-260806/REQ-2, session-260806/REQ-4, docs/azents/spec/domain/conversation.md | existing |

## 12. Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Unbounded active-session list consumption in `AgentFocusedShell` | session-260806/ADR-D1 | Directory page query and sidebar-summary query | Agent shell and related tRPC consumer paths | No shell consumer requests unbounded active rows. |
| Unbounded archived-session list consumption and sidebar archived section | session-260806/REQ-3, session-260806/ADR-D1 | Archived directory page query and directory restore UI | Sidebar props, archived query wiring, controls, and rendering | No sidebar archived query, loading/error state, or archived section remains. |
| Current active/archived unbounded route response contracts at current consumers | session-260806/ADR-D1 | Paginated directory and sidebar-summary contracts | API route schemas, generated clients, tRPC routers, tests | No current web consumer expects an unbounded session-list response. |
| Persistent data, archive retention policy, session ownership, and subagent visibility model | None; retained | Existing sources remain authoritative | Not applicable | Schema and existing domain invariants remain unchanged. |

## 13. Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-08-06`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5, M6`
- Approved scope: paginated Agent session directory, server-composed bounded sidebar summary, and coherent session-list refresh behavior.
