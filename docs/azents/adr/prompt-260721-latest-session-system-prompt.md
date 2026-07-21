---
title: "Latest Session System Prompt"
created: 2026-07-21
tags: [chat, observability, storage, architecture]
---

# Latest Session System Prompt

- Snapshot: [prompt-260721/REQ](../requirements/prompt-260721-latest-session-system-prompt.md)
- Document reference: `prompt-260721/ADR`

## Context

The Context inspector exposes only the latest system prompt, while the event transcript currently stores a complete prompt-analysis payload on every turn marker. The append-only event model is appropriate for turn usage and boundaries but is not appropriate for a replaceable diagnostic view.

## Decisions

### ADR-D1. Store one replaceable prompt snapshot per AgentSession

Affected requirements: [prompt-260721/REQ-1](../requirements/prompt-260721-latest-session-system-prompt.md#req-1-latest-prompt-inspection), [prompt-260721/REQ-2](../requirements/prompt-260721-latest-session-system-prompt.md#req-2-bounded-diagnostic-storage), and [prompt-260721/REQ-3](../requirements/prompt-260721-latest-session-system-prompt.md#req-3-existing-data-transition).

Persist one session-keyed system prompt snapshot outside the event transcript. Successful model-output admission upserts the latest assembled prompt analysis in the same transaction. A successful call without an assembled system prompt removes the snapshot.

The Context inspector reads this snapshot directly and does not fall back to historical turn-marker payloads.

### ADR-D2. Transition existing prompt data forward

Affected requirement: [prompt-260721/REQ-3](../requirements/prompt-260721-latest-session-system-prompt.md#req-3-existing-data-transition).

The schema migration copies the newest stored prompt analysis per session into the session-keyed snapshot and removes the `system_prompt` member from legacy turn-marker payloads. The migration does not preserve prompt history.

## Consequences

- Event transcript growth no longer includes repeated system prompt bodies.
- The latest prompt remains available to the existing Context inspector after refresh.
- Historical prompt inspection is intentionally unavailable.
- Updating JSONB event rows leaves dead tuples for PostgreSQL maintenance; normal autovacuum reclaims reusable space, while immediate file-size reduction requires an operator-scheduled table rewrite.
