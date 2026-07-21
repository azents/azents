---
title: "Sequential Input Buffer Preparation Historical Requirements Reconstruction"
created: 2026-07-12
implemented: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sequential-260712
historical_reconstruction: true
migration_source: "docs/azents/design/sequential-input-buffer-preparation.md"
---

# Sequential Input Buffer Preparation Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sequential-260712`
- Source: `docs/azents/design/sequential-260712-sequential-input-buffer-preparation.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The current input-buffer path combines queue draining with run creation and model-call boundaries. It claims compatible FIFO chunks, groups inputs by requested inference profile, promotes `action_message` envelopes into durable history, and may inject matching inputs into an already running AgentRun. Message-kind behavior, inference resolution, event append, action side effects, and turn continuation are therefore coupled in one service.

This creates several problems:

- FIFO correctness depends on chunk selection and worker ownership assumptions.
- Model target resolution is delayed until AgentRun activation even though the input message owns the override.
- Historical message inference fields require later run association or mutation to describe resolved state.
- TurnAction envelopes leak from queue storage into durable transcript history.
- Edit creates a special pending buffer even though it is an idle-only durable history rewrite.
- Processor failures, preparation-only actions, and active-run continuation cannot be represented by one boolean.
- The central service accumulates dependencies and branching for every buffer and action type.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Treat input-buffer processing as preparation for the next turn.
- Process exactly one durable FIFO item at a time until the queue is empty.
- Start or continue a turn only after the final empty-buffer check.
- Give each buffer/action kind an isolated polymorphic processor.
- Resolve model and effort overrides while processing the message that applies them.
- Store the current resolved inference configuration on AgentSession.
- Allow different turns in one AgentRun to use different models.
- Keep actual provider/model execution provenance internal and out of the chat UI contract.
- Preserve durable semantic events without equating persistence with model visibility.
- Make handled preparation failures durable, non-retryable, and non-blocking.
- Linearize input acceptance, FIFO processing, and turn claim through the AgentSession row lock.
- Remove deprecated or unnecessary buffer kinds and background execution infrastructure.

## Non-goals

- Do not add a new FIFO sequence column or Session sequence counter. UUIDv7 Buffer id ordering remains the queue order for this change.
- Do not redesign the existing frontend pending/live-state architecture.
- Do not expose physical provider/model identity in the chat UI.
- Do not preserve compatibility readers for removed `edited_user_message`, `background_completion`, or durable `action_message` behavior.
- Do not make third-party or dynamically registered input-buffer processors.
- Do not change unrelated FastAPI background jobs, asyncio implementation tasks, or Runtime exec process handling.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
