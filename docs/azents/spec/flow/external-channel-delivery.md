---
title: "External Channel Delivery and Channel Work"
created: 2026-07-22
tags: [backend, engine, external-channel, slack, delivery]
spec_type: flow
owner: "@Hardtack"
touches_domains: [external-channel, agent, conversation, toolkit]
code_paths:
  - python/apps/azents/src/azents/core/external_channel_progress.py
  - python/apps/azents/src/azents/core/external_channel_file.py
  - python/apps/azents/src/azents/core/slack_external_channel_progress.py
  - python/apps/azents/src/azents/engine/tools/external_channel.py
  - python/apps/azents/src/azents/engine/tools/deps.py
  - python/apps/azents/src/azents/engine/tooling/execution_context.py
  - python/apps/azents/src/azents/engine/run/resolve.py
  - python/apps/azents/src/azents/services/external_channel/channel_action.py
  - python/apps/azents/src/azents/services/external_channel/file_transfer.py
  - python/apps/azents/src/azents/services/external_channel/event_processor.py
  - python/apps/azents/src/azents/services/external_channel/slack_events.py
  - python/apps/azents/src/azents/repos/external_channel/management.py
  - python/apps/azents/src/azents/repos/external_channel/management_data.py
  - python/apps/azents/src/azents/repos/external_channel/work.py
  - python/apps/azents/src/azents/repos/external_channel/work_data.py
  - python/apps/azents/src/azents/worker/session/idle_continuation.py
  - typescript/apps/azents-web/src/features/session-channels/**
last_verified_at: 2026-07-23
spec_version: 11
---

# External Channel Delivery and Channel Work

## Explicit Publication Boundary

Normal model output is never relayed to Slack. The only model-facing publication path is the direct unprefixed `channel_action` tool. It is exposed only when the root AgentSession has at least one active External Channel binding and receives the current binding/work snapshot in its execution context.

A tool call must identify a binding owned by the current Agent and Session. The tool supports two atomic modes:

- `continue`: optionally send one conversational reply, replace the current
  provider-neutral work title, and replace the ordered Channel Work task list.
- `finish`: send one required final reply and finish Channel Work.

Either mode may attach up to 20 absolute Runtime paths to its conversational reply.
File-bearing calls always require non-empty text and do not introduce a separate upload
action. Text-only calls retain the existing behavior.

Task updates require a concise current-work title in the same call. Guidance tells
the Agent to use the participant's language, concrete progressive wording, and an
ellipsis, for example `Investigating error logs…`. A title-only update is valid
only after tasks exist. Message-only continuation does not change canonical
progress or its desired revision.

Tasks use `pending`, `in_progress`, `completed`, or `failed`, with at most 49
ordered tasks in one action. They have stable IDs and may include literal details,
literal output, and ordered labeled HTTP or HTTPS sources. The complete serialized
desired snapshot must fit 64 KiB; an oversized update is rejected before canonical
state changes so accepted continuation context is never silently truncated. Each
binding has independent work state even when several bindings share one AgentSession.
The ordinary Session Todo toolkit is not the Channel Work source of truth.

## Durable Commit Before Provider Calls

`ExternalChannelActionService.execute` commits the canonical action, work mutation, task snapshot, and every provider delivery intent in one database transaction. Only after commit does it attempt each pending delivery.

Provider calls occur without an open database transaction. A delivery is claimed from `pending` to `attempting` before the call and finishes as exactly one of:

- `delivered`: provider confirmed success and returned a provider message identity when applicable;
- `failed`: provider confirmed rejection or the committed payload/credentials are invalid;
- `unknown`: cancellation, timeout, or ambiguous transport outcome prevents safe classification.

Provider mutations are never automatically retried. Stale `attempting` recovery marks an ambiguous outcome conservatively instead of re-executing the call. An explicit Slack `ok: false` response not covered by a specialized provider error is a confirmed `failed` result with the bounded Slack error code retained in its sanitized summary; it is not classified as a transport-ambiguous `unknown` result.

## File-bearing Reply Delivery

Before the action transaction commits, the service resolves each absolute Runtime path,
requires a readable regular file with a positive size, derives a bounded filename and
media type, and enforces the effective outbound per-file and aggregate byte limits. Any
missing, unreadable, unsupported, oversized, or recovered-without-source file fails before
provider mutation. The committed action and existing `REPLY` delivery store only ordered
manifests containing path, filename, media type, and expected size.

After commit, Slack delivery processes files sequentially:

1. acquire one `files.getUploadURLExternal` target for each manifest;
2. read the Runtime source in ordered 1 MiB chunks without whole-file `get()`;
3. require the streamed byte count to match the preflight size exactly;
4. upload directly to the provider target; and
5. after every stream succeeds, call `files.completeUploadExternal` exactly once with
   ordered file IDs, the conversational text, channel, and root thread.

A failed acquisition or stream prevents completion. Confirmed provider rejection,
missing scope, rate limit, or unavailable Runtime source is `failed`. Upload or
completion transport ambiguity is `unknown`. No phase is automatically replayed, and
ordinary Agent output is never uploaded without the explicit Channel action.

## Activity Tracker Lifecycle

- Conversational replies use `chat.postMessage` with Slack `markdown_text` in the bound thread. The Tool schema and the provider delivery boundary enforce Slack's current 12,000-character Markdown limit before a mutation request.
- Releasing the first eligible invocation while a binding has no unanswered work creates Channel Work and one Block Kit Activity Tracker intent before Session wake-up. Creation does not depend on Todo state or a `channel_action` call.
- Initial binding activation separately creates one button-only `Open Azents session`
  control message. Later invocations on the binding do not repeat it, and Activity
  Tracker desired state never contains the Session URL.
- The initial Tracker states that the Agent is checking the message with one
  `task_card` carrying the `in_progress` state. Once Channel Work exists, one
  `plan` block carries the Agent-authored title and complete ordered task list.
  Nested tasks use `task_id`, literal title, Slack status, and optional literal
  rich-text details/output plus labeled URL sources. They omit standalone
  `task_card` block types. The Plan sends no `plan_id`, is read-only, and requires
  no Slack interaction callback.
- Task or title changes update the retained provider message with the complete
  latest Block Kit payload through `chat.update`. A revision-derived provider-only
  `block_id` changes for each message iteration. Slack Agent streaming methods are
  not used.
- Finishing requires a final reply. The reply is attempted first; only a durable
  `delivered` result permits `chat.delete` for the Tracker. Failed, unknown, or
  not-attempted replies leave deletion `not_attempted`.
- A later work cycle creates a new Tracker rather than reusing the deleted cycle's
  provider identity.

The work cycle stores its title, complete provider-neutral version-2 desired
snapshot, desired revision, and retained provider identity. A matching Slack
deletion event or confirmed
`message_not_found` update clears that identity and commits one replacement create
only while work is active and desired state exists. Ambiguous provider outcomes and
finished work do not trigger replacement. If work advances while a replacement
create is in flight, delivery commits and attempts one follow-up update for the
replacement identity and latest desired revision.

Tracker creation and final-reply completion may race. Both completion paths
idempotently ensure the finished action's delete intent after the reply is delivered
and a provider Tracker identity exists. A Tracker delete that returns
`message_not_found` is reconciled as already absent and never recreates the Tracker.

## Approval Control Messages

Authorization control messages use Block Kit with a URL button and accessible
fallback text; they do not expose an approval URL as ordinary body text. Provider
participant labels and IDs are rendered in Slack plain-text objects so untrusted
mrkdwn cannot create mentions, links, or formatting.

Slack API validation responses for approval controls are confirmed
`failed/provider_rejected` outcomes. Only transport or server ambiguity is
`unknown/provider_ambiguous`.

Every compatible final approval decision creates a delete intent for a successfully
delivered control message in the same transaction as the decision, then attempts
that provider delete after commit. Deny and block use the access request's route and
do not require a Session binding. Cleanup failure or ambiguity remains visible
without changing the final decision.

Control delivery and the access decision may complete in either order. A pending
request never deletes its control message. After a delivered control result commits,
a separate reconciliation transaction locks the request before the control delivery
and creates the same idempotent delete intent if the request is already final. This
lock order matches the decision transaction and avoids request/control lock
inversion. Whichever path observes both prerequisites attempts the pending delete;
the delivery claim preserves one provider mutation.

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

- **2026-07-23** (spec_version 11) — Added file-bearing `channel_action` replies,
  pre-commit Runtime manifests and limits, sequential 1 MiB streaming, one ordered Slack
  completion, and one-attempt failure/ambiguity outcomes.
- **2026-07-23** (spec_version 10) — Added Agent-authored progress titles, rich provider-neutral task snapshots, Slack-native complete Plan lowering without streaming, and confirmed approval-control rejection classification.
- **2026-07-23** (spec_version 8) — Removed summary-card progress chrome whenever Todo cards exist so the active Todo exclusively owns the circular indicator.
- **2026-07-23** (spec_version 7) — Reconciled approval decisions with late control-message delivery so either completion order creates and consumes one idempotent delete intent without lock inversion.
- **2026-07-23** (spec_version 6) — Separated the one-time Session-link message, switched the Tracker to native read-only task cards, limited work to 49 Todos, made successful final replies delete the Tracker, and restricted replacement to active desired work with race-safe cleanup reconciliation.
- **2026-07-23** (spec_version 5) — Rendered provider participant identity in approval controls as Slack plain text rather than untrusted mrkdwn.
- **2026-07-23** (spec_version 4) — Added automatic pre-execution Activity Tracker creation, one-message checking/working/completed transitions, delivered-final-reply completion gating, retained normal completion, confirmed-deletion recreation, and latest-revision replacement reconciliation.
- **2026-07-23** (spec_version 3) — Added post-decision approval-control deletion and delivery-derived Activity Tracker projection states with canonical task presentation.
- **2026-07-23** (spec_version 2) — Added Slack Markdown reply payloads, provider-bound length validation, and Block Kit operational/approval delivery with accessible fallback text.
- **2026-07-22** (spec_version 1) — Promoted direct `channel_action`, binding-scoped Channel Work, commit-before-call delivery, terminal outcomes, one-attempt Slack operations, continuation, and cleanup delivery.
