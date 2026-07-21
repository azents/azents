---
title: "External Watch / Raw Session Event Subscription Historical Requirements Reconstruction"
created: 2026-05-03
implemented: 2026-05-03
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: external-260503
historical_reconstruction: true
migration_source: "docs/azents/design/external-watch-raw-session-subscription.md"
---

# External Watch / Raw Session Event Subscription Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `external-260503`
- Source: `docs/azents/design/external-260503-external-watch-raw-subscription.md`
- Historical source date basis: `2026-05-03`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

This document is the design for [#3332](https://github.com/azents/azents/issues/3332). It abandons structure that mapped external channel events such as Slack/Discord to `ConversationSession` units, and changes to structure where external watch directly injects events into agent raw session.

Assumptions of parent design are below.

- `1 Agent = 1 raw session`
- External platforms such as Slack/Discord/GitHub/Jira already provide their own thread/channel/ticket/issue as work unit.
- NoIntern does not create separate `ConversationSession` per external context; it appends external event to agent raw session event stream.
- External response is not automatic reply routing. Agent explicitly specifies output tool target and executes it.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

1. Represent external channel/thread/issue/ticket subscriptions as common `ExternalWatch` domain.
2. Convert external event into common raw session event envelope.
3. Replace existing Slack/Discord session mapping creation path with watch-based routing.
4. Do not automatically bind external response target to event origin; make it explicit through output tool contract.
5. Provide only hooks for future access policies such as Personal agent, and handle concrete policy in subsequent implementation.

## Non-goals

- Existing `slack_sessions` / `discord_sessions` data backfill.
- Migration preserving existing thread history as NoIntern session history.
- Completion of Personal agent DM-only/private access policy.
- Merging Scheduler itself into `ExternalWatch` table.
- Full removal of `ConversationSession` runtime ownership. This is scope of #3331/#3338.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

- `EngineWorker` shards per-session runner by `session_id` of message received from broker.
- When receiving `SessionMessage`, it updates `conversation_sessions.run_state`, `last_activity_at`, `run_heartbeat_at`, and notifies sandbox manager of activity.
- Stuck recovery creates `RESUME` message with `ConversationSession` record.
- Therefore, first implementation of #3332 provides bridge to use `session_id = agent.raw_session_id`, and removal of `ConversationSession` runtime fields is completed in #3331/#3338.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
