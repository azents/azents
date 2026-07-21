---
title: "Unify Subagent Communication Through Mailbox Activity Historical Requirements Reconstruction"
created: 2026-07-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: unify-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0168-unify-subagent-communication-through-mailbox-activity.md"
---

# Unify Subagent Communication Through Mailbox Activity Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `unify-260719`
- Source: `docs/azents/adr/unify-260719-unify-subagent-communication-through-mailbox-activity.md`
- Historical source date basis: `2026-07-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Subagent collaboration currently uses two observation paths. Ordinary `send_message` communication is stored as target-session `agent_message` mailbox input, while `wait_agent` reads terminal child results directly from `AgentRun` projections and advances a separate observation cursor. As a result, an agent blocked in `wait_agent` does not react to ordinary mailbox communication, and terminal-result coordination requires separate delivery, cursor, and polling behavior.

The session wake contract is already source-specific and must remain stable: `send_message` queues mailbox input without starting a target turn, while `spawn_agent` and `followup_task` mark the target session running and send the normal payload-free broker wake-up.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
