---
title: "Present Chat Activity as an Ordered Event Stream Historical Requirements Reconstruction"
created: 2026-07-20
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: chat-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0174-present-chat-activity-as-an-ordered-event-stream.md"
---

# Present Chat Activity as an Ordered Event Stream Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `chat-260720`
- Source: `docs/azents/adr/chat-260720-chat-activity-as-an-ordered-event-stream.md`
- Historical source date basis: `2026-07-20`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[group-260720/ADR](../adr/group-260720-group-chat-activity-in-the-frontend.md) moved continuous chat tool work into a frontend-owned `Activity` presentation, but the implemented presentation introduced three problems:

1. the collapsed activity uses a large bordered card that visually dominates the conversation;
2. its summary exposes implementation counts such as model turns and tool calls instead of the kinds of work performed; and
3. expansion regroups calls into semantic phases, separating reasoning from tools and destroying the original event order.

Reasoning and other internal work events are also projected inconsistently: an event may appear inside or outside an activity depending on whether a tool group already exists. The product requires one predictable rule for all internal work events.

The activity summary must support first-party builtins without hard-coding every dynamically installed Toolkit tool. Toolkit products may also have multiple installations, but installation identity is detail rather than top-level activity-summary information.

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
