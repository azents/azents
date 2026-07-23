---
title: "External Channel Delivery and Channel Work"
created: 2026-07-22
tags: [backend, engine, external-channel, slack, delivery]
spec_type: flow
owner: "@Hardtack"
touches_domains: [external-channel, agent, conversation, toolkit]
code_paths:
  - python/apps/azents/src/azents/engine/tools/external_channel.py
  - python/apps/azents/src/azents/engine/tools/deps.py
  - python/apps/azents/src/azents/engine/tooling/execution_context.py
  - python/apps/azents/src/azents/engine/run/resolve.py
  - python/apps/azents/src/azents/services/external_channel/channel_action.py
  - python/apps/azents/src/azents/services/external_channel/slack_events.py
  - python/apps/azents/src/azents/repos/external_channel/work.py
  - python/apps/azents/src/azents/repos/external_channel/work_data.py
  - python/apps/azents/src/azents/worker/session/idle_continuation.py
  - typescript/apps/azents-web/src/features/session-channels/**
last_verified_at: 2026-07-22
spec_version: 1
---

# External Channel Delivery and Channel Work

## Explicit Publication Boundary

Normal model output is never relayed to Slack. The only model-facing publication path is the direct unprefixed `channel_action` tool. It is exposed only when the root AgentSession has at least one active External Channel binding and receives the current binding/work snapshot in its execution context.

A tool call must identify a binding owned by the current Agent and Session. The tool supports two atomic modes:

- `continue`: optionally send one conversational reply and replace the ordered Channel Work task list.
- `finish`: optionally send one final reply and finish/clear Channel Work.

Tasks use `pending`, `in_progress`, or `completed`. Each binding has independent work state even when several bindings share one AgentSession. The ordinary Session Todo toolkit is not the Channel Work source of truth.

## Durable Commit Before Provider Calls

`ExternalChannelActionService.execute` commits the canonical action, work mutation, task snapshot, and every provider delivery intent in one database transaction. Only after commit does it attempt each pending delivery.

Provider calls occur without an open database transaction. A delivery is claimed from `pending` to `attempting` before the call and finishes as exactly one of:

- `delivered`: provider confirmed success and returned a provider message identity when applicable;
- `failed`: provider confirmed rejection or the committed payload/credentials are invalid;
- `unknown`: cancellation, timeout, or ambiguous transport outcome prevents safe classification.

Provider mutations are never automatically retried. Stale `attempting` recovery marks an ambiguous outcome conservatively instead of re-executing the call.

## Slack Operations

- Conversational replies use `chat.postMessage` in the bound thread.
- Creating unfinished tasks creates one separate progress message.
- Task changes update that provider message with `chat.update`.
- Finishing or clearing all tasks deletes it with `chat.delete`.
- A later new work cycle creates a new progress message rather than reusing a deleted one.

The progress message identity and drift/error state are durable management data. A failed or unknown projection never replaces canonical Channel Work state.

## Continuation

A successfully completed run with unfinished Channel Work remains eligible for idle continuation. Continuation is binding-aware and includes the current unfinished work snapshot. Sending an intermediate reply does not finish active work. Completing/clearing tasks, or explicitly finishing with no follow-up work, stops continuation for that binding. Other active bindings can still require continuation in the same Session.

## Cleanup Delivery

Binding disconnect, connection disconnect, Session archive, and decommission may commit progress-delete intents. Lifecycle transactions never call Slack directly. The post-commit consumer attempts each current cleanup intent once; unresolved attempts remain visible as failed or unknown without rolling back the terminal lifecycle transition.

## Changelog

- **2026-07-22** (spec_version 1) — Promoted direct `channel_action`, binding-scoped Channel Work, commit-before-call delivery, terminal outcomes, one-attempt Slack operations, continuation, and cleanup delivery.
