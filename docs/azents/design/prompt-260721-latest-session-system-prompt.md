---
title: "Latest Session System Prompt Design"
created: 2026-07-21
implemented: 2026-07-21
tags: [chat, observability, storage, backend]
---

# Latest Session System Prompt Design

- Requirements: [prompt-260721/REQ](../requirements/prompt-260721-latest-session-system-prompt.md)
- ADR: [prompt-260721/ADR](../adr/prompt-260721-latest-session-system-prompt.md)
- Document reference: `prompt-260721/DESIGN`

## Current Gap

`TurnMarkerPayload` currently embeds `SystemPromptAnalysisPayload`. Every successful model-output admission appends a new turn marker, but the Context inspector selects only the latest embedded value. This retains repeated prompt fragments and final composed text without a consumer for earlier copies.

## Design

### Persistence

Add a session-keyed persistence row containing the complete `SystemPromptAnalysisPayload` and its update timestamp. `session_id` is the primary key and a cascading foreign key to `agent_sessions`.

### Output Admission

During the existing successful model-output transaction:

1. persist provider metadata and normalized output events;
2. append the usage-only turn marker;
3. upsert the prepared system prompt analysis for the session, or delete the existing row when analysis is absent;
4. clear retry state and continue existing phase behavior.

The snapshot repository uses PostgreSQL conflict update on `session_id`; no separate transaction or eventual-consistency worker is introduced.

### Context Projection

The Context service loads the session snapshot in the same read transaction as recent events. It uses that snapshot for both System Prompt output and the `system` character breakdown. The response contract remains unchanged.

### Existing Data Transition

The Alembic migration creates the snapshot table, copies the highest model-order legacy prompt payload per session, and strips the obsolete `system_prompt` member from turn-marker JSON payloads. It does not retain a compatibility reader.

The JSON update frees logical payload ownership immediately. PostgreSQL table-file shrink is an operational concern: autovacuum reclaims dead space for reuse, and immediate disk release requires an operator-scheduled table rewrite outside the migration transaction.

## Traceability

| Requirement | ADR decision | Design mechanism |
| --- | --- | --- |
| prompt-260721/REQ-1 | ADR-D1 | Session-keyed snapshot read by Context |
| prompt-260721/REQ-2 | ADR-D1 | Turn marker omits prompt analysis; snapshot upsert replaces prior value |
| prompt-260721/REQ-3 | ADR-D2 | Forward backfill and JSON payload cleanup |

## Failure Handling

- If output admission rolls back, the prompt snapshot update rolls back with it.
- If no system prompt is assembled for a successful call, the previous snapshot is deleted so the inspector does not report stale state.
- Session deletion cascades to the snapshot row.

## Test Strategy

### Primary verification matrix

| Scenario | Expected result |
| --- | --- |
| Successive model calls with different prompts | One session snapshot contains only the second prompt |
| Successful model call with no prompt | Existing snapshot is removed |
| Turn marker serialization | No system prompt field is stored |
| Context inspector projection | Snapshot supplies prompt detail and system breakdown |
| Legacy payload migration | Latest legacy prompt is copied and all legacy event prompt fields are removed |

### Verification plan

- Add focused repository, execution, and Context projection tests.
- Run backend Ruff, Pyright, and targeted pytest suites.
- Run migration upgrade coverage against the existing PostgreSQL test environment.

No new testenv fixture or external credential is required because this change does not alter user-visible model invocation.
