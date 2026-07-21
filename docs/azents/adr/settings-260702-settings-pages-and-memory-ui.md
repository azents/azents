---
title: "Agent Settings Pages and Memory UI"
created: 2026-07-02
tags: [frontend, api, memory, agent, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: settings-260702
historical_reconstruction: true
migration_source: "docs/azents/adr/0088-agent-settings-pages-and-memory-ui.md"
---

# settings-260702/ADR: Agent Settings Pages and Memory UI

## Context

Agent Memory is already stored in PostgreSQL and exposed to model execution through dedicated tools. Users can ask an agent to save, list, read, search, and delete Memory entries, but there is no product UI for inspecting or correcting those entries.

The current Agent settings page is a single long page that mixes avatar/profile editing, model configuration, capability toggles, administrator management, runtime reset, and Agent deletion. Adding Memory CRUD directly into that page would make the page harder to scan and would mix long-lived operational data management with form settings.

The product needs a transparent way to inspect and edit Agent Memory while also improving Agent settings information architecture first.

## Decision

### settings-260702/ADR-D1. Agent settings becomes a page hub with dedicated subpages

The `/settings` route becomes an Agent settings hub rendered as grouped list/table rows. Each row represents a settings area and links to a dedicated subpage.

The settings routes are:

- `/settings` — settings hub
- `/settings/profile` — profile, avatar, visibility, enabled state
- `/settings/model` — model selection, model parameters, max turns
- `/settings/capabilities` — shell, toolkits, subagents, built-in tools
- `/settings/memory` — memory enabled state and Memory item management
- `/settings/admins` — Agent administrators
- `/settings/danger` — runtime reset and Agent deletion

### settings-260702/ADR-D2. Memory UI is a settings subpage, not a session tab

Memory management belongs under Agent settings at `/settings/memory`. The page is not a chat session tab because Memory is Agent-level persistent state, not per-session working context.

### settings-260702/ADR-D3. Memory UI access separates read and write by scope

Agent-scope Memory can be read by users who can view the Agent. Agent-scope Memory can be created, edited, and deleted only by Agent administrators or workspace owners.

User-scope Memory can be read, created, edited, and deleted only by the current authenticated user. The UI must not expose another user's user-scope Memory to Agent administrators or workspace owners.

### settings-260702/ADR-D4. Human UI uses strict CRUD semantics

The existing `save_memory` tool keeps name-based upsert semantics for model execution. The human UI uses strict CRUD semantics:

- create fails with conflict when another Memory in the same scope already uses the submitted name;
- update and delete target Memory by immutable `id`;
- update can change the Memory name, but conflicts with another entry in the same scope are rejected.

### settings-260702/ADR-D5. Ship settings IA and Memory as stacked phases

Ship the work as two stacked phases:

1. Agent settings pages: settings hub and subpage information architecture, preserving existing settings behavior.
2. Agent Memory settings: Memory API, generated clients, tRPC router, `/settings/memory` page, and Memory row in the settings hub.

### settings-260702/ADR-D6. Memory revision and restore are out of scope

The initial Memory UI does not add soft delete, revisions, audit history, or restore. The design must leave room for later actor-aware audit/revision support, but the first implementation uses the existing `agent_memories` source table.

## Consequences

### Positive

- Agent settings become easier to scan before Memory is added.
- Memory management has a dedicated operational workspace with room for search, filters, and editors.
- Human edits avoid silent overwrites while preserving model tool upsert behavior.
- User-scope Memory remains private to the current user.
- Stacked phases keep review and QA scope manageable.

### Negative

- The settings refactor adds routing and component work before Memory UI lands.
- Users must navigate into subpages instead of editing all settings on one page.
- Initial Memory UI cannot restore accidental deletes.

## Alternatives

| Alternative | Reason rejected |
| --- | --- |
| Add Memory CRUD into the existing single settings page | The page is already dense, and Memory CRUD is an operational data surface rather than a simple setting. |
| Add Memory as a chat session tab | Memory is Agent-level long-lived state, not session-local working context. |
| Let all Agent viewers edit agent-scope Memory | Shared Memory quality would be too easy to change accidentally and would not match Agent settings write permissions. |
| Reuse model-tool name upsert semantics in the UI | Silent overwrite is unsafe for human create flows and makes name changes ambiguous. |
| Add soft delete or full revision history now | It expands schema, API, UI, and QA scope beyond the first transparency/editing feature. |

## Migration provenance

- Historical source filename: `0088-agent-settings-pages-and-memory-ui.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
