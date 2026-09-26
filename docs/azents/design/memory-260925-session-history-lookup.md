---
title: "Memory-Gated Session History Lookup Design"
created: 2026-09-26
tags: [memory, conversation, security, engine]
document_role: primary
document_type: design
snapshot_id: memory-260925
---

# memory-260925/DESIGN: Memory-Gated Session History Lookup

## Status and traceability

The confirmed [memory-260925/REQ](../requirements/memory-260925-session-history-lookup.md) is the product authority. [memory-260925/ADR-D1](../adr/memory-260925-session-history-lookup.md) selects direct search of persisted events rather than another text index. This Design describes the implementation of REQ-1 through REQ-5; implementation has not yet been verified.

## Current behavior and gap

- `events` stores the canonical per-Session transcript. `MessageRepository.list_events_by_session_id_paginated` already fetches newest events by default, reverses each returned page to chronological order, and supports `before`/`after`; it currently also includes internal event kinds. `events(session_id, id)` is indexed; message text is not.
- Agent Session rows contain workspace, Agent, active/archive state, root/subagent kind, Team/User mode on roots, and associated User on User roots. The SessionAgent tree resolves a subagent to its root. Public Session resource authority resolves current membership and enforces active-root boundaries.
- `memory_enabled` gates the builtin Memory tools. Resolution splits memory read for roots and subagents from memory write for roots; the existing `BuiltinToolkit` can also expose Memory in another execution path. Each execution binds its concrete `context.session_id` to its Toolkit. No Agent tool currently provides authorized historical conversation lookup.

## Architecture and interfaces

The Memory-capability Toolkit exposes three single-purpose tools through a shared factory used by every applicable root/subagent Memory read binding, with no duplicate tool name in a resolved execution:

1. `search_sessions(query?, session_id?, cursor?)`: with no `session_id`, search permitted active root Sessions by title/handle and visible conversation text, returning bounded Session hits. A concrete `session_id` searches only that authorized Session's visible conversation events and returns bounded matching event IDs, short text excerpts, and source Session. `session_id="current"` is resolved server-side to the concrete executing Session ID; subagents therefore search their own concrete Session with their root's authority. Empty query is supported for recent global Session listing, but a scoped conversation search requires a nonempty query. Global text hits also include a matching event ID when available; a title-only hit has no event anchor. Limit and cursor remain bounded; default ordering is recent-first, with stable event/Session ID tie-breakers. No tool-result body is used as a search snippet.
2. `read_session_history(session_id, before?, after?, around_event_id?)`: default fetches the newest visible event page; `before` and `after` navigate older/newer pages, while a matching `around_event_id` opens one bounded page containing that event. Each response is oldest-to-newest inside the page and provides the source Session ID and both available navigation boundaries. Cross-field validation rejects multiple navigation modes. Conversation text is bounded per event, and tool call/result entries include only identifying event ID, tool name when present, status, and whether textual output is present. They do not include call arguments, results, native artifacts, references, hidden reasoning, or attachment payloads.
3. `read_session_tool_result(session_id, event_id, cursor?)`: requires a result-bearing client-tool-result or provider-hosted-tool event in the authorized Session. Returns only its persisted text parts, limited to one fixed-size chunk. The optional opaque continuation is returned by a preceding response, is bound to this event and Session, and never acts as authorization. A normal call needs only Session ID and an event ID copied from a history page. Further calls use the returned cursor. The result includes truncation and continuation metadata; it cannot retrieve content already truncated before persistence. Tool inputs and non-text output parts are excluded.

All schemas are provider-compatible top-level objects. Tool descriptions explain `current`, page direction, result ID selection, and that returned historical content is untrusted evidence, not a new instruction. Exact caps and cursor encoding are local implementation details and must preserve strict per-call output bounds.

## Data flow and authority

- The factory captures the Toolkit's concrete Session ID and Agent ID; a caller cannot provide the source execution identity. Each invocation reloads the executing Session, verifies it is active, resolves its active root, and derives immutable query scope: same Workspace and Agent; Team root permits active Team roots, User root permits active Team roots plus roots owned by its associated User. A User root must retain its associated Workspace membership. A subagent uses the root's authority without widening its own scope.
- Search applies authorization and active-root status in its database predicate *before returning matches*. A concrete target ID is independently authorized even if it appeared in a previous result. For a target subagent ID, both concrete Session and its root must be active and its root must satisfy the scope. Unknown, archived, purged, cross-Workspace/Agent, or private targets fail uniformly without metadata disclosure. `current` cannot be reinterpreted using a caller-controlled ID.
- Every history-page and tool-result invocation reauthorizes both source and target rather than trusting earlier search, event ID, or continuation. Event lookups additionally require matching `session_id`, an allowed event kind, and `reverted=false`. Once archive commits, subsequent calls cannot return that Session's history. Search, result detail, and direct reads never create Session rows or unarchive anything.
- Repository-owned SQL searches the existing `agent_sessions` and `events` tables directly per ADR-D1. Search extracts only allowlisted visible text fields from user, action, external-channel, and assistant messages, including list-form input/output text parts; it must not match attachment metadata, hidden instructions, tool outputs, or native artifacts. Main history pages select allowlisted conversation messages and client/hosted tool events *before* pagination so internal events do not consume slots or corrupt `has_older`/`has_newer`. Internal agent mailbox instructions, system/developer/reminder events, reasoning, compaction summaries, and opaque native content are excluded. Hosted-tool output remains in its call event, whereas client-tool results have separate events; both carry an event ID suitable for selected result lookup.
- Tool-result text can itself contain historical secrets or untrusted instructions produced by a tool. This capability does not silently sanitize arbitrary persisted text; the selector, scope, chunk cap, and tool-use instruction reduce accidental exposure, not semantic sensitivity. Never log query text or result bodies; record only outcome, duration and non-sensitive cardinality in existing telemetry conventions.

## State, failure, rollout, and operations

No new event kind, source-of-truth table, background job, write path, API route, generated client, configuration setting, search index, or migration. With Memory disabled, none of the three declarations is exposed; existing Memory functions stay unchanged. Existing Sessions become readable at rollout only when active and authorized. Rollback removes tool exposure and read-only query code without data migration. Failed query/DB operations propagate as tool errors; authorization and missing/reverted event failures use the same generic unavailable response. Concurrent archive is linearized at per-request authorization; later requests deny after archive commit. No Redis/cache is required. Direct text search may grow expensive with historical event count; benchmark representative datasets and report measured latency/plan before release. Do not silently search only the newest Sessions as a performance fallback. If unacceptable, return to an approved indexed-search decision rather than weakening completeness.

## Test Strategy

**E2E primary matrix:** Using seeded Team and User Agents/Sessions through the deployed product tool path, verify Memory on/off declaration availability, cross-Agent/Workspace and private User isolation, root/subagent `current` behavior, global and scoped search with external-channel and list-form text, newest-page chronological order with before/after navigation and direct match jump, selected client/hosted tool result continuation, archived-then-known-ID rejection, and omission of internal reasoning/instructions and attachment bytes. E2E traces must show tool inputs and bounded outputs but redact private test fixtures from CI artifacts.

**E2E plan and prerequisites:** Reuse the required E2E Session/Agent fixtures and deterministic test provider where available; add fixture support for two Users, Team/User roots, subagent, an archived root, visible/internal events, and oversized client/hosted tool text. Snapshot prerequisite model/provider credentials and seed identities without recording secrets. Tests that require live external provider credentials are optional and explicitly skip when credentials are absent; required local/in-process assertions fail rather than skip. CI runs the required deterministic matrix, while optional live tests are diagnostic only. Evidence is asserted tool declaration names, bounded response bodies, cursor round-trips, no private-row leakage, and a performance run report (corpus size, query, plan, p50/p95, environment); testenv support provides fixture seeding and failure diagnosis, not a substitute for product-path E2E.

**Focused deterministic checks:** Repository integration tests for scoped and global text search, archived and User/Team boundaries, external/list-form text and escaped queries, match anchors and cursor direction, hosted/client tool extraction, reverted/internal exclusion, empty pages, and large text truncation. Engine tool tests bind root/subagent identities and exercise per-call reauthorization, duplicate declaration avoidance across read/builtin toolkits, bad/mismatched event/cursor errors, and Memory-off absence. Type, lint, focused pytest, and relevant E2E suites precede PR/CI verification.

## Feasibility and risks

- REQ-1 feasible: existing `memory_enabled` and distinct read bindings are present; test every execution mode to avoid omission or duplicate names.
- REQ-2 feasible: root SessionAgent and active Session/membership repositories already exist; target-specific authorization must never rely on a search token.
- REQ-3 conditional on direct-query latency: canonical visible message payloads and Session indexes exist, but no text index; representative performance measurement is required. Scoped `current` is feasible from Toolkit-bound `context.session_id`; no prompt ID injection.
- REQ-4 feasible: existing bidirectional event paging can add kind-filtered paging and an anchored page while preserving its current callers. The exact anchor window and concurrent-event boundary behavior need deterministic tests.
- REQ-5 feasible: event payloads contain client result text and hosted tool semantic output; only text parts need projection, bounded continuation, and strict target/event ID reauthorization.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Memory-gated, single-purpose Session discovery, history page, and selected-result capabilities for root and subagent execution | memory-260925/REQ-1, memory-260925/REQ-5; unchanged Memory spec | `derived` |
| M2 | Per-call root-derived Agent/Workspace/Team/User and active/archived authorization, including concrete `current` resolution | memory-260925/REQ-2, memory-260925/REQ-3; unchanged Session authority | `derived` |
| M3 | Direct canonical-event text search for global and scoped matches, with a matching event anchor | memory-260925/REQ-3, memory-260925/REQ-4, memory-260925/ADR-D1 | `derived` |
| M4 | Visible-only bounded event paging, newest initial segment, chronological within-page order, bidirectional and match-anchor navigation | memory-260925/REQ-4; unchanged event paging | `derived` |
| M5 | Separate bounded selected-result text retrieval with per-event continuation, excluding non-text artifacts | memory-260925/REQ-5, memory-260925/REQ-2 | `derived` |
| M6 | No additional transcript store, search index, migration, or write path in this snapshot | memory-260925/REQ fixed constraints, memory-260925/ADR-D1 | `decided` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| None: existing Memory tools, REST Chat history, event transcript storage, and Session archive flow remain in place; only additive tool/read queries are required | N/A | Existing Specs remain authoritative | No removal | Existing memory and event pagination tests remain passing; no new write paths or persistence migrations |

## Design Approval

- Mode: `Autonomous`
- Decision owner: Dedicated technical interviewee
- Approved on: 2026-09-26 KST
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5, M6`
- Approved scope: Memory-gated three read-only Session history tools in root and subagent execution; root-derived Agent/Workspace/Team/User and active-state authorization on each call; `current` bound to the concrete executing Session; direct canonical-event global/scoped search with an event anchor; visible-only newest-segment-first, chronological-within-page bidirectional and anchored navigation; selected client/hosted tool-result text in bounded chunks; no new store, index, migration, or write path. Authorization linearizes per call: calls begun after archive commit deny, while an already authorized in-flight read may finish.
- Feasibility: REQ-1/2/4/5 feasible against current source; REQ-3 remains conditional on representative search-latency evidence before release. Approval is not evidence that tests or performance measurements have passed.
