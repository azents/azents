---
title: "Memory-Gated Session History Lookup Requirements"
created: 2026-09-25
updated: 2026-09-26
tags: [memory, conversation, security]
document_role: primary
document_type: requirements
snapshot_id: memory-260925
---

# Memory-Gated Session History Lookup Requirements

- Snapshot: `memory-260925`
- Document reference: `memory-260925/REQ`

## Problem

An Agent that needs to verify a remembered claim cannot currently find an earlier Session and inspect its original conversation through its Memory capability. Persisted Session history is available to the product, but not as a bounded Agent capability. Giving the Agent unrestricted access to stored event data would expose unrelated or private conversations and overwhelm model input.

## Primary Context

### Primary Actor

An Agent executing in a Session with Memory enabled.

### Primary Scenario

While answering a request that refers to earlier work, the Agent finds a permitted earlier Session, retrieves a bounded portion of that Session's persisted conversation, and uses the visible evidence to answer without accessing conversations outside its permitted scope.

## Supporting Scenarios or Effects

- The Agent can continue reading a long permitted history in bounded portions instead of receiving the entire Session at once.
- A known Session identifier can be used to read directly without first searching.
- When the relevant Session is known, the Agent can search within that Session instead of searching all permitted Sessions. The active execution Session can be chosen without recalling its identifier.
- The Agent can inspect a specific part of a permitted Session's tool results when the conversation alone is insufficient, without receiving every tool result by default.
- An Agent without Memory enabled receives no Session-history capability.
- Denied, missing, or removed Sessions cannot be distinguished by leaked private metadata.

## Goals

- Allow discovery and evidence-backed recall from already persisted Session history.
- Preserve current Agent, Workspace, and User Session privacy boundaries.
- Treat an archived Session as deleted for Agent search and history lookup.
- Prevent unbounded past-event output from entering the model context.
- Keep historical tool-result text opt-in and confined to the requested portion of history.

## Non-Goals

- Automatic extraction, consolidation, or saving of long-term memories.
- A new rollout storage format or changes to the durable event source of truth.
- Exposing internal model reasoning or system/developer instructions as historical evidence.

## Requirements

### REQ-1. Memory-gated availability

The Session-history lookup capability is available only to an Agent executing with its Memory feature enabled.

**Acceptance criteria**

- An eligible execution can find permitted Sessions and request persisted history for a known Session identifier.
- The capability is absent from the Agent's available tools when Memory is disabled.

### REQ-2. Authorized historical evidence

The Agent can retrieve persisted conversation evidence only from a Session it is authorized to access under the existing Agent, Workspace, and User Session privacy boundaries.

**Acceptance criteria**

- A request for a Session belonging to a different Agent or Workspace is denied without exposing its contents or metadata.
- A Team Session can find and read Team Sessions for the same Agent and Workspace but no private User Sessions.
- A User Session can find and read its associated User's private Sessions and Team Sessions for the same Agent and Workspace, but no other User's private Sessions.
- Access through a subagent does not widen the root Session's authority.
- Missing, inaccessible, archived, or purged records fail without revealing which condition applied.

### REQ-3. Discoverable permitted Sessions

The Agent can find earlier permitted Sessions without knowing their identifiers in advance, or find a particular conversation location within a specified permitted Session. Search results use the same access boundary as history lookup.

**Acceptance criteria**

- Search returns bounded results with enough source information to select a Session for history lookup.
- A specified Session identifier restricts matches to that Session, and choosing the current execution Session does not require its identifier to be present in model context.
- Matches within a specified Session identify their conversation location so the Agent can inspect the relevant bounded segment without traversing every newer page.
- A Team Session never discovers a private User Session, and a User Session never discovers another User's private Session.
- Different Agents, Workspaces, and archived Sessions do not appear in search results; specifying an inaccessible Session does not disclose whether it exists.

### REQ-4. Bounded and usable history

The Agent can inspect a limited segment of permitted history and navigate to another segment to verify a specific earlier statement or tool outcome.

**Acceptance criteria**

- A response identifies the source Session and retained event boundaries and is bounded independently of the total Session size.
- An initial request starts with the most recent bounded segment, presented oldest-to-newest within that segment.
- The Agent can move to both older and newer adjacent segments without reloading an unbounded transcript.
- A matching conversation location from search can be opened directly as a bounded history segment.
- Ordinary history lookup identifies tool activity but does not return every tool result's text by default.
- Private internal instructions, hidden reasoning, and raw attachment bytes are not presented as conversation evidence.

### REQ-5. On-demand tool-result detail

The Agent can request text from tool results in a specifically selected, bounded portion of a permitted Session's history when needed to verify a prior outcome.

**Acceptance criteria**

- Tool-result text appears only after an explicit request for a specific portion of history, not in general Session search or ordinary history pages.
- The Agent can identify the portion to request from bounded history pages without first loading the full transcript.
- A detail request cannot exceed the same Session access scope or return an unbounded amount of result text; it does not include raw attachment bytes, hidden reasoning, or private internal instruction events.

## Fixed Constraints

- Current Sessions persist a durable event transcript; this capability does not create another source of truth.
- Current Memory is an Agent capability with separate Agent and User scope semantics; enabling this capability must not erase the root Session's User/Team boundary.
- Archive retention and purge policy continue to govern underlying storage, but an archived Session must be unavailable to this capability immediately, regardless of physical retention.
- The tools must be straightforward to use. When a single multi-mode tool makes searching, browsing, and selecting one result confusing, prefer a separate dedicated operation for the selected tool result.

## Open Assumptions

- None that changes the requested product scope. Search query semantics and event presentation are design questions constrained by these requirements.

## Confirmation

Confirmed by the requester on 2026-09-26 KST as a complete revised snapshot: discovery and bounded lookup, Agent/Workspace and Team/User privacy boundaries, archive-as-deleted behavior, most-recent-first-segment and bidirectional navigation, on-demand selected tool-result text through a straightforward dedicated operation, and scoped search by known Session identifier or `current` without exposing the current ID in model context.
