---
title: "Separate Input Payload and Control Action with DB Source of Truth Historical Requirements Reconstruction"
created: 2026-06-15
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: input-260615
historical_reconstruction: true
migration_source: "docs/azents/adr/0061-input-control-plane-clean-migration.md"
---

# Separate Input Payload and Control Action with DB Source of Truth Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `input-260615`
- Source: `docs/azents/adr/input-260615-input-control-plane-clean-migration.md`
- Historical source date basis: `2026-06-15`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[chat-260519/ADR](../adr/chat-260519-chat-input-buffer.md) decided to store user chat input in the `input_buffers` table and promote it to durable event at model-call boundary. [rest-260605/ADR](../adr/rest-260605-rest-chat-write-boundary.md) moved Web chat writes to REST commit boundary and defined REST success as input buffer commit.

However, several payload carriers still remain in current engine ingress.

- `SessionMessage.messages` directly carries user input in broker payload.
- `SessionEditMessage` returns edited input through `SessionMessage.messages` again after history rewrite.
- `BackgroundCompletionMessage` carries background operation result as broker message and then lowers it to user-role model input.
- Slash command has executor lifecycle separate from input buffer, creating resolve/state handling paths duplicated with session runner lifecycle.
- If user stop is delivered only through broker signal, it can be lost in the very situations where users most often press stop: stuck/broker/runner abnormal states.

This structure turns Redis broker into a durable queue and distributes source of truth for input and control action. This change assumes production clean state and simplifies ingress model without intermediate compatibility layer.

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
