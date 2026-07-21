---
title: "Latest Session System Prompt Requirements"
created: 2026-07-21
updated: 2026-07-21
implemented: 2026-07-21
tags: [chat, observability, storage]
document_role: primary
document_type: requirements
snapshot_id: prompt-260721
---

# Latest Session System Prompt Requirements

- Snapshot: `prompt-260721`
- Document reference: `prompt-260721/REQ`

## Problem

System prompt diagnostic data is appended to every completed model turn even though the Context inspector shows only the current prompt. Long-lived sessions therefore retain repeated large prompt bodies and cause unnecessary database growth.

## Primary Actor

Workspace member investigating an AgentSession through the Context inspector.

## Primary Scenario

After an AgentSession completes one or more model calls, the workspace member opens the System Prompt view and sees the system prompt from the latest successful model call after refreshing the page.

## Supporting Scenarios

- A model call with no system prompt clears any previously shown system prompt for that session.
- Existing sessions preserve their latest inspectable prompt when the storage behavior changes.

## Goals

- Keep only the latest system prompt diagnostic state for each AgentSession.
- Preserve the current Context inspector experience for the latest prompt.
- Stop future per-turn duplication of system prompt bodies in the transcript.

## Non-Goals

- Historical per-turn or per-run system prompt inspection.
- Prompt-diff, audit-history, or replay features.
- Changing model-visible prompt assembly.

## Requirements

### REQ-1. Latest prompt inspection

The Context inspector must present the system prompt used by the latest successful model call for the selected session.

**Acceptance criteria**

- After a refresh, the System Prompt view shows the latest successful model call's agent, toolkit, injected, and final prompt analysis.
- A successful model call without a system prompt leaves the System Prompt view empty for that session.

### REQ-2. Bounded diagnostic storage

System prompt diagnostic storage must remain bounded to one current value per AgentSession rather than growing with model turns.

**Acceptance criteria**

- New turn-marker events do not persist system prompt analysis bodies.
- Repeated successful model calls for one session do not create multiple retained prompt-analysis bodies.

### REQ-3. Existing data transition

The storage transition must retain the latest inspectable prompt for existing sessions while removing obsolete repeated prompt-analysis bodies from transcript events.

**Acceptance criteria**

- An existing session with prompt analysis retains its latest value after upgrade.
- Existing turn-marker payloads no longer retain system prompt analysis after the transition.

## Fixed Constraints

- The latest prompt update must commit atomically with successful model-output admission.
- The session's normal deletion lifecycle must remove its diagnostic prompt state.
- No legacy read fallback is retained after the transition.

## Open Assumptions

- PostgreSQL autovacuum or an operator-scheduled table rewrite reclaims physical space from obsolete event-row versions after the logical cleanup.

## Confirmation

Confirmed by the requester on 2026-07-21 before ADR and design decisions began.
