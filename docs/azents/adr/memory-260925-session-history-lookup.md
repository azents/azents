---
title: "Memory-Gated Session History Lookup Technical Decisions"
created: 2026-09-26
tags: [memory, conversation, security, performance]
document_role: primary
document_type: adr
snapshot_id: memory-260925
---

# memory-260925/ADR: Session History Lookup

## Context

The confirmed [memory-260925/REQ](../requirements/memory-260925-session-history-lookup.md) requires an Agent with Memory enabled to find permitted active Sessions and inspect bounded conversation history. Tool-result text is retrieved only when a particular result is selected through an easy-to-use dedicated operation. The event transcript in PostgreSQL remains authoritative, and archived Sessions are unavailable even while their rows are retained.

The current `events` table has indexes on Session identity and event order, but no index for searchable message text. Search must still apply the root Session's Agent, Workspace, Team/User, and active status boundary before exposing any match. Search results must not disclose tool-result text.

## Material decision map

- Fixed by memory-260925/REQ-1 through REQ-5: Memory-gated exposure; root-derived privacy boundary; archived-is-unavailable behavior; bounded newest-segment-first history with chronological within-page order and bidirectional navigation; on-demand bounded result text through a straightforward dedicated operation.
- D1, accepted: Search the canonical events directly for this snapshot, without introducing a persisted search representation or new index.
- Agent-owned implementation details: exact tool names and local input fields, filtering of non-conversation event kinds, pagination cursor format, fixed output caps, and where to place helper modules. These cannot introduce a new permission or visibility mode.

## memory-260925/ADR-D1: Conversation text search strategy

**Affected requirements:** memory-260925/REQ-2, memory-260925/REQ-3, memory-260925/REQ-4.

**Question:** How should initial search locate text in permitted historical conversation events while retaining the event transcript as the sole source of truth?

- **Option A — Query canonical events directly:** Filter eligible active root Sessions and visible message event types, then search their persisted text at request time. No new persisted state or migration. Search may slow as the number and size of stored events grows; verify performance and identify when an index is warranted.
- **Option B — Add a maintained PostgreSQL text-search index:** Keep events authoritative but add a derived indexed representation of searchable conversation text. More predictable large-history search, at the cost of migration, index storage/write overhead, backfill or expression maintenance, and stronger correctness checks that archived Sessions and private events remain invisible.

**Decision:** Option A. Search eligible active root Sessions and canonical visible conversation event text directly. Do not add a separate search representation, text index, or schema migration in this snapshot. Validate search latency on representative data before release. If measured latency becomes unacceptable, pursue an indexed search strategy as a separate future development snapshot rather than silently limiting the historical search scope.

**Decision owner:** Requester (Collaborative mode).

**Accepted:** 2026-09-26 KST. This decision does not authorize implementing the feature before the complete Design is approved.

**Consequences:** The initial change has no search-specific persistence migration or write-path maintenance. Search cost may rise with retained event volume; performance evidence and an observable fallback-free failure plan must accompany Design validation. Search must not omit old permitted Sessions merely to bound database work.
