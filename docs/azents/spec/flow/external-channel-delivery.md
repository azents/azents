---
title: "External Channel Delivery and Channel Work"
created: 2026-07-22
tags: [backend, engine, external-channel, slack, delivery]
spec_type: flow
owner: "@Hardtack"
touches_domains: [external-channel, agent, conversation, toolkit]
code_paths:
  - python/apps/azents/src/azents/core/external_channel_activity.py
  - python/apps/azents/src/azents/engine/tools/external_channel.py
  - python/apps/azents/src/azents/engine/tools/deps.py
  - python/apps/azents/src/azents/engine/tooling/execution_context.py
  - python/apps/azents/src/azents/engine/run/resolve.py
  - python/apps/azents/src/azents/services/external_channel/channel_action.py
  - python/apps/azents/src/azents/services/external_channel/event_processor.py
  - python/apps/azents/src/azents/services/external_channel/slack_events.py
  - python/apps/azents/src/azents/repos/external_channel/management.py
  - python/apps/azents/src/azents/repos/external_channel/management_data.py
  - python/apps/azents/src/azents/repos/external_channel/work.py
  - python/apps/azents/src/azents/repos/external_channel/work_data.py
  - python/apps/azents/src/azents/worker/session/idle_continuation.py
  - typescript/apps/azents-web/src/features/session-channels/**
last_verified_at: 2026-07-23
spec_version: 4
---

# External Channel Delivery and Channel Work

## Explicit Publication Boundary

Normal model output is never relayed to Slack. The only model-facing publication path is the direct unprefixed `channel_action` tool. It is exposed only when the root AgentSession has at least one active External Channel binding and receives the current binding/work snapshot in its execution context.

A tool call must identify a binding owned by the current Agent and Session. The tool supports two atomic modes:

- `continue`: optionally send one conversational reply and replace the ordered Channel Work task list.
- `finish`: send one required final reply and finish Channel Work.

Tasks use `pending`, `in_progress`, or `completed`. Each binding has independent work state even when several bindings share one AgentSession. The ordinary Session Todo toolkit is not the Channel Work source of truth.

## Durable Commit Before Provider Calls

`ExternalChannelActionService.execute` commits the canonical action, work mutation, task snapshot, and every provider delivery intent in one database transaction. Only after commit does it attempt each pending delivery.

Provider calls occur without an open database transaction. A delivery is claimed from `pending` to `attempting` before the call and finishes as exactly one of:

- `delivered`: provider confirmed success and returned a provider message identity when applicable;
- `failed`: provider confirmed rejection or the committed payload/credentials are invalid;
- `unknown`: cancellation, timeout, or ambiguous transport outcome prevents safe classification.

Provider mutations are never automatically retried. Stale `attempting` recovery marks an ambiguous outcome conservatively instead of re-executing the call.

## Activity Tracker Lifecycle

- Conversational replies use `chat.postMessage` with Slack `markdown_text` in the bound thread. The Tool schema and the provider delivery boundary enforce Slack's current 12,000-character Markdown limit before a mutation request.
- Releasing the first eligible invocation while a binding has no unanswered work creates Channel Work and one Block Kit Activity Tracker intent before Session wake-up. Creation does not depend on Todo state or a `channel_action` call.
- The initial Tracker states that the Agent is checking the message. Every presentation includes top-level accessible fallback `text` and an `Open Azents session` URL button.
- Task changes update the retained provider message with a complete working-state Block Kit payload through `chat.update`. Task titles use plain-text objects.
- Finishing requires a final reply. The reply is attempted first; only a durable `delivered` result permits the completion update. Failed, unknown, or not-attempted replies leave completion `not_attempted`.
- Normal completion updates the same Tracker to a retained `Answer complete` state without active task content. It does not call `chat.delete`.
- A later work cycle creates a new Tracker rather than reusing the completed cycle's provider identity.

The work cycle stores its desired Tracker payload, desired revision, and retained
provider identity. A matching Slack deletion event or confirmed
`message_not_found` update clears that identity and commits one replacement create.
Ambiguous provider outcomes do not trigger replacement. If work advances while a
replacement create is in flight, delivery commits and attempts one follow-up update
for the replacement identity and latest desired revision.

## Approval Control Messages

Authorization control messages use Block Kit with a URL button and accessible fallback text; they do not expose an approval URL as ordinary body text.

Every compatible final approval decision creates a delete intent for a successfully
delivered control message in the same transaction as the decision, then attempts
that provider delete after commit. Deny and block use the access request's route and
do not require a Session binding. Cleanup failure or ambiguity remains visible
without changing the final decision.

The Activity Tracker identity and delivery state are durable management data.
Session Channels renders the canonical ordered task snapshot and one derived
projection state:

- `synchronized`: desired progress has a retained provider message and no unresolved latest operation;
- `missing`: progress is desired but no provider message identity exists;
- `stale`: the latest create/update is unresolved or failed, or a provider message remains when no progress is desired;
- `delete_failed`: the latest delete failed or was not attempted;
- `unknown`: the latest provider mutation has an ambiguous result;
- `none`: no progress is desired and no provider message identity remains.

State and desired-progress revision counters remain diagnostic metadata and are not
compared as one sequence. A failed or unknown projection never replaces canonical
Channel Work state.

## Continuation

A successfully completed run with unfinished Channel Work remains eligible for idle continuation. Continuation is binding-aware and includes the current unfinished work snapshot. Sending an intermediate reply does not finish active work. Completing/clearing tasks, or explicitly finishing with no follow-up work, stops continuation for that binding. Other active bindings can still require continuation in the same Session.

## Cleanup Delivery

Binding disconnect, connection disconnect, Session archive, and decommission may commit Tracker-delete intents. Lifecycle transactions never call Slack directly. The post-commit consumer attempts each current cleanup intent once; unresolved attempts remain visible as failed or unknown without rolling back the terminal lifecycle transition.

## Changelog

- **2026-07-23** (spec_version 4) — Added automatic pre-execution Activity Tracker creation, one-message checking/working/completed transitions, delivered-final-reply completion gating, retained normal completion, confirmed-deletion recreation, and latest-revision replacement reconciliation.
- **2026-07-23** (spec_version 3) — Added post-decision approval-control deletion and delivery-derived Activity Tracker projection states with canonical task presentation.
- **2026-07-23** (spec_version 2) — Added Slack Markdown reply payloads, provider-bound length validation, and Block Kit operational/approval delivery with accessible fallback text.
- **2026-07-22** (spec_version 1) — Promoted direct `channel_action`, binding-scoped Channel Work, commit-before-call delivery, terminal outcomes, one-attempt Slack operations, continuation, and cleanup delivery.
