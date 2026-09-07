---
title: "External Channel Delivery and Channel Work"
created: 2026-07-22
tags: [backend, engine, external-channel, slack, discord, delivery]
spec_type: flow
owner: "@Hardtack"
touches_domains: [external-channel, agent, conversation, toolkit]
code_paths:
  - python/apps/azents/src/azents/core/external_channel_progress.py
  - python/apps/azents/src/azents/core/external_channel_file.py
  - python/apps/azents/src/azents/core/external_channel_session_presence.py
  - python/apps/azents/src/azents/core/external_channel_title.py
  - python/apps/azents/src/azents/core/slack_external_channel_progress.py
  - python/apps/azents/src/azents/engine/tools/external_channel.py
  - python/apps/azents/src/azents/engine/tools/deps.py
  - python/apps/azents/src/azents/engine/tooling/execution_context.py
  - python/apps/azents/src/azents/engine/run/resolve.py
  - python/apps/azents/src/azents/runtime/transfer/runtime_to_provider.py
  - python/apps/azents/src/azents/services/external_channel/channel_action.py
  - python/apps/azents/src/azents/services/external_channel/discord_http.py
  - python/apps/azents/src/azents/services/external_channel/file_transfer.py
  - python/apps/azents/src/azents/services/external_channel/mailbox_ingestion_store.py
  - python/apps/azents/src/azents/services/external_channel/presentation.py
  - python/apps/azents/src/azents/services/external_channel/provider_control.py
  - python/apps/azents/src/azents/services/external_channel/slack_events.py
  - python/apps/azents/src/azents/services/external_channel/discord_delivery.py
  - python/apps/azents/src/azents/services/external_channel/discord_sdk.py
  - python/apps/azents/src/azents/services/external_channel/discord_gateway.py
  - python/apps/azents/src/azents/services/external_channel/discord_gateway_manager.py
  - python/apps/azents/src/azents/services/external_channel/slack_presence.py
  - python/apps/azents/src/azents/services/external_channel/slack_presence_manager.py
  - python/apps/azents/src/azents/services/external_channel/gateway_runtime.py
  - python/apps/azents/src/azents/services/external_channel/discord_presentation.py
  - python/apps/azents/src/azents/services/external_channel/thread_title.py
  - python/apps/azents/src/azents/services/session_title.py
  - python/apps/azents/src/azents/services/scheduled_task/channel.py
  - python/apps/azents/src/azents/services/scheduled_task/control.py
  - python/apps/azents/src/azents/services/exchange_file/**
  - python/apps/azents/src/azents/services/session_resource_authority.py
  - python/apps/azents/src/azents/repos/external_channel/management.py
  - python/apps/azents/src/azents/repos/external_channel/management_data.py
  - python/apps/azents/src/azents/repos/external_channel/work.py
  - python/apps/azents/src/azents/repos/external_channel/work_data.py
  - python/apps/azents/src/azents/repos/external_channel/work_state.py
  - python/apps/azents/src/azents/worker/session/idle_continuation.py
  - typescript/apps/azents-web/src/features/session-channels/**
last_verified_at: 2026-09-07
spec_version: 56
---

# External Channel Delivery and Channel Work

## Explicit Publication Boundary

Normal model output is never relayed to a provider. The only model-facing publication
path is the unprefixed `channel_action` tool. It is available only when the root
AgentSession has at least one connected External Channel binding. When Tool Search is
enabled, `channel_action` and `download_external_file` are deferred discovery targets;
when disabled, the complete catalog exposes them directly.

The active Toolkit contributes a minimal static prompt stating that ordinary assistant
output is not delivered and that external publication, participant-input requests,
continuation, and silent completion use `channel_action`. Normal turns do not reload
canonical Channel Work into a dynamic prompt.
Mode selection, binding-handle, Channel Work, and file-materialization guidance lives
in tool descriptions and field schemas. Compaction alone preserves unfinished binding,
provider, resource, title, and ordered task continuity while excluding revisions,
projection diagnostics, and provider-effect outcomes.

A tool call must identify a binding owned by the current Agent and Session. Every
model input boundary exposes four atomic modes:

- `continue`: optionally send one conversational reply, replace the current
  provider-neutral work title, and replace the ordered Channel Work task list.
- `request_input`: send one required ordinary question or feedback request while
  preserving active Work. Confirmed delivery pauses automatic continuation for only
  that binding until newly created same-binding human input or `continue`.
- `finish`: send one required final reply and finish Channel Work.
- `ignore`: finish existing active Work silently, regardless of recorded task status.
  It accepts no message, title, task update, or files. The transition advances the
  existing Work revisions, sets its finish time, and clears desired progress while
  retaining current provider projection observation until cleanup settles. It returns
  one deletion effect for each current `PRESENT` Activity Tracker on only the selected
  binding and executes those effects without a final reply. No reply, progress
  create/update, file, or unrelated provider request occurs.

`channel_action` may use the same binding and mode in consecutive model turns.
Publication frequency is determined by the Agent's work and communication needs
rather than a process-local repetition guard.

The `continue`, `request_input`, and `finish` modes may attach up to 20 file sources
to their conversational reply. Each source
must use one of two formats: an absolute POSIX Runtime file path beginning with `/`, or
an authority-checked `exchange://{object_key}` file-location URI. Relative paths,
`artifact://`, `azents://`, and other URI schemes are rejected. The path format selects
current Runtime file storage or server-managed Exchange storage respectively. Mixed
Exchange and Runtime-path calls require current Runtime file storage. File-bearing calls
always require non-empty text and do not introduce a separate upload action. Text-only
calls retain the existing behavior.

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
The canonical value is one Session-bound Toolkit State identity composed from the
Agent, Session, namespace `external_channel`, and state name
`channel_work:{binding_id}`. Its schema-version-5 payload stores the stable
`work_cycle_id`, current or latest work lifecycle, desired progress, and ordered
provider projection parts plus nullable `awaiting_input_run_id`. One service instance
serializes complete Actions for the same Binding while allowing different Bindings to
proceed independently. The awaiting marker
is valid only for active Work, is not exposed through public management state, and is
cleared by terminal or replacement transitions. Whole-state optimistic-lock retries
are isolated per binding.
The ordinary Session Todo toolkit is not the Channel Work source of truth.

## Agent Presentation

On multi-app connections, every Slack or Discord output associated with an Agent
starts with that Agent's current display name in bold. This applies to conversational
replies, checking/progress controls, route-resolved approval controls, errors, and
file-bearing publication. Single-app connections rely on their dedicated App identity
and do not repeat an Agent-name line above messages. App-level selector controls have
no selected Agent and do not invent one. The name is provider presentation only and
does not alter canonical source text or execution authority.

When the validated Slack installation exposes the required message-customization
capability and the Agent has a provider-safe image URL, delivery may override the
message icon. Missing capability, missing or invalid image data, or provider rejection
falls back to the normal App icon without failing the underlying delivery. Agent
identity is therefore always present through the required bold name even when icon
customization is unavailable.

## Canonical Commit and Immediate Provider Effects

Slack Web API mutations execute through the public SDK client. Discord
text/thread/message mutations execute through the pinned `discord.py` Client's
isolated private HTTP adapter so one caller-owned multi-operation effect reuses the
same authenticated aiohttp session and SDK rate-limit state without high-level
channel or message prefetches. Azents invokes each operation once inside the existing
deadline and adds no fallback or post-ambiguity replay. Direct transport remains only
for Discord multipart file-message create, Discord CDN attachment bytes, Slack
private-file bytes, and Slack external-upload bytes; each retains its exact origin,
length, chunk, authority, and one-attempt contract.

`ExternalChannelActionService.execute` commits the canonical Channel Work transition
before provider I/O and returns an ordered tuple of process-local effect plans. It then
revalidates the current Agent, Session, binding, resource, route, connection,
credentials, capability, and effect-specific authority before attempting each effect
without an open database transaction.

The Tool result contains one identifier-free outcome for each ordered effect:

- `delivered`: the provider confirmed the mutation;
- `failed`: the provider confirmed rejection or current validation failed;
- `unknown`: timeout, cancellation, or another ambiguous provider result prevents safe
  classification; or
- `not_attempted`: current provider authority is unavailable or a dependent earlier
  effect did not complete.

The result includes only the operation, ordered part, status, and sanitized reason or
detail, plus the final Work revision and whether awaiting input was established.
Normal Session client-tool call/result events are the only durable
Agent-requested execution history. No Channel Action, delivery attempt, pending
provider work item, retry, replay, recovery, or compensation record is created.

For `request_input`, the initial canonical transition clears an older awaiting marker,
advances `state_revision`, and captures the exact Work cycle and revision before
provider I/O. Awaiting settlement occurs only after every ordinary reply part is
`delivered`. The settlement uses the existing bounded Toolkit State CAS and succeeds
only for the captured active cycle and revision; failed, unknown, not-attempted, or
stale delivery remains ready for normal continuation. Process loss after delivery but
before settlement therefore fails open rather than silently waiting.

Progress effect results compare-and-set only the current Work-owned projection part
inside the binding's Toolkit State for the expected work cycle and desired revision.
A stale result cannot overwrite a newer cycle or desired snapshot. Reply results have
no separate durable projection. Confirmed Slack API
rejection is `failed`; transport or server ambiguity is `unknown`.

Discord Create Message uses a bounded operation key derived from the current Tool call
and ordered effect and sends `enforce_nonce=true`. The key is a provider duplicate
fence for that live operation, not durable replay authority. Credential, permission,
missing-message, rate-limit, and confirmed provider rejection outcomes are `failed`;
network, timeout, invalid success payload, and server ambiguity are `unknown`. An
unknown write is not replayed automatically.

## Provider File Download

A model-visible file key uses the single direct-address contract:

```text
external-file:v1:<provider>:<binding>:<channel>:<message>:<file>
```

Slack leaves channel and message empty and resolves the provider file ID through the
configured App. Discord requires channel, message, and attachment identity and calls the
provider directly with those coordinates. The download path validates current Agent,
Session, connected binding, route, configured credentials, capability, and the
displayed declared size before streaming. Transient Gateway/Socket health is not an
outbound authorization input. Provider credentials and permissions are authoritative. It
does not query Session event history to recover provider coordinates and retains no
fallback for the replaced shorter key shape.

## File-bearing Reply Delivery

Before the canonical Work transaction commits, the Tool resolves each source and enforces the
effective outbound per-file and aggregate byte limits. Runtime sources must be readable
regular files with a positive size. Exchange sources must resolve under the current
canonical `SessionResourceAuthority`; their metadata and returned byte length must agree.
Any missing, unauthorized, expired, unreadable, unsupported, oversized, or
unavailable file fails before provider mutation. Ordered manifests containing source
kind, source reference, filename, media type, and expected size remain in the current
Tool effect only; External Channel does not persist a file-delivery record.

After commit, every Runtime manifest creates one metadata-only Runtime transfer attempt
through the existing trusted transfer coordinator.
The trusted provider-delivery service resolves the current Runtime when the file-bearing
Tool executes, claims the verified transfer object, resolves its opaque object handle only
inside trusted backend code, and exposes only a bounded async byte stream to Slack. The ordered batch retains every Runtime consumer claim
until the one `files.completeUploadExternal` result. Runtime source bytes never use ordinary
`FileStorage.read_range` relay and never create ExchangeFile, Artifact, ModelFile, or
FilePart resources.

Slack processes files sequentially:

1. acquire one `files.getUploadURLExternal` target for each manifest;
2. immediately before each Slack request, verify that every Runtime claim remains active;
3. stream the verified Runtime object or re-resolve and verify an Exchange source under the
   current execution authority, with each yielded byte sequence bounded and matched to the
   committed expected size;
4. upload directly to the provider target; and
5. after every stream succeeds, call `files.completeUploadExternal` exactly once as form
   data with ordered file IDs serialized in `files`, the conversational text, channel,
   and root thread.

Slack `delivered` requires provider completion followed by acknowledgement and
settlement of every Runtime consumer claim. A confirmed pre-provider failure abandons
and cancels only the current Runtime attempts. If provider work has started and its
result is ambiguous, or if post-provider settlement cannot be confirmed, the Tool
effect is `unknown`; Runtime claims follow their existing bounded expiry lifecycle.
External Channel creates no persistent recovery work and does not replay the transfer
or provider mutation.

If a Runtime transfer cannot be admitted, verified, claimed, or streamed, the current
Tool effect fails before provider mutation. Exchange-only replies retain their
authority-resolved bounded stream path, and ordinary Agent output is never uploaded
without the explicit Channel action.

Discord splits oversized replies into stable ordered message parts. Each part is
bounded to the provider message limit, preserves balanced fenced Markdown where
possible, and is one ordered process-local effect. A Channel Work snapshot
instead becomes one retained compact Embed Tracker. The Embed title contains the
bounded work title, and its description contains completion/failure counts plus every
ordered task's status marker and bounded title. Remaining description space is
assigned to status-prioritized details or output and then labeled sources without
dropping a task. The functional Tracker body is not duplicated as ordinary message
content.
Discord file-bearing messages stream a bounded multipart body from the
already-authorized Runtime or Exchange source manifest. The multipart request includes
the current effect's bounded operation key, validates each emitted byte count against
preflight size, and is bounded by the provider request limit. Neither External Channel
rows nor Session history retain file bytes, provider upload URLs, credentials, or
provider identifiers.

For a Discord root-message thread Resource, the first route-resolved outbound effect ensures
one provider thread and records its returned channel ID on the resource under a lock.
New thread creation uses the current routed Agent name after trimming and provider
length bounding, with the safe product fallback only for a blank name. Existing
threads are reused without rename, and later Agent renames do not rename them. Only a
direct successful thread create records the exact normalized provisional name beside
the delivery channel ID. A thread observed before create or recovered after an
ambiguous create outcome receives no automatic-title evidence.
Parent-channel Resources deliver directly to the provider parent channel. Slack omits
`thread_ts`; Discord never provisions a thread. Thread Resources retain the existing
target behavior: Slack uses the bound root and Discord reuses an existing thread or
provisions one delivery thread. New Discord provider threads explicitly use the
current connection-owned automatic archive duration, restricted to 60, 1440, 4320, or
10080 minutes and defaulted to 1440 by setup and migration. The value is read for a new
create operation only. Existing, reused, and reconciled threads are never updated when
the connection policy changes. All later approval, Session navigation, reply, file,
progress, and cleanup effects use the Resource's explicit target. A failed or ambiguous thread
creation returns that immediate outcome and does not cause automatic replay.

After the matching External Channel Session title is successfully committed as
`auto_generated`, one separate system-owned best-effort operation may revalidate the
exact active Discord Session, Binding, Resource, route, Agent, connection, Guild,
credentials, and retained thread target. It performs one GET. If the current title
already equals the final title, it ends without PATCH; if the current title no longer
equals the retained provisional title, it preserves provider ownership and ends. Only
the remaining match sends one adjacent name-only PATCH. Missing state, provider
failure, cancellation, ambiguity, or process interruption ends the operation without
retry, reconciliation, backfill, durable attempt state, or impact on the committed
Session title and Agent execution.

## Activity Tracker Lifecycle

- Conversational replies use `chat.postMessage` with Slack `markdown_text` in the bound thread. The Tool schema and the provider delivery boundary enforce Slack's current 12,000-character Markdown limit before a mutation request.
- Releasing new conversational input while a binding has no unanswered work creates a
  Channel Work cycle before Session wake-up. Slack and Discord cycles are visible for
  an eligible explicit invocation and hidden for an ordinary message admitted by an
  existing all-messages Binding. Initial checking visibility does not depend on a
  `channel_action` call.
- Initial binding acceptance separately creates one Session presence control and the
  eligible initial Activity Tracker plan in the same transaction as the triggering
  mailbox input. Every Binding creation is mention-gated, so its initial cycle is
  visible. The versioned presence control replaces the former button-only Session link.
  Slack uses Block Kit and Discord uses an Embed; both state that the current Agent
  joined the conversation and place `View session` and provider-native
  `Conversation settings` actions below the message while the Binding remains
  connected. The ingress caller attempts every returned plan once only after the
  canonical commit and HTTP/provider acknowledgement boundary. Failure, ambiguity,
  cancellation, or process termination creates no recovery work and does not gate the
  mailbox, wake, or AgentRun. Later invocations on the binding do not repeat the
  joined-presence mutation, and Activity Tracker desired state never contains the
  Session URL.
- The initial conversational Tracker states that the Agent is checking the message
  with one `task_card` carrying the `in_progress` state. A Scheduled Task run instead
  states `Agent is running a scheduled task…` on the first line and the task title on
  the second line while keeping the objective out of the initial status. Once Channel
  Work exists, one `plan` block carries the Agent-authored title and complete ordered
  task list.
  Nested tasks use `task_id`, literal title, Slack status, and optional literal
  rich-text details/output plus labeled URL sources. They omit standalone
  `task_card` block types. The Plan sends no `plan_id`, is read-only, and requires
  no Slack interaction callback. Initial creation and every complete conversational
  update append Block Kit `View session` and signed Binding-scoped
  `Conversation settings` actions derived from current canonical authority. Scheduled
  Task Trackers omit the conversation settings action.
- Task or title changes update the retained provider message with the complete
  latest Block Kit payload through `chat.update`. A revision-derived provider-only
  `block_id` changes for each message iteration. Slack Agent streaming methods are
  not used.
- Hidden Slack or Discord Work commits initial checking state without a Tracker. A valid
  Agent-authored `continue` transition with at least one unfinished task promotes the
  same cycle to visible inside the canonical Work mutation and plans a create from the
  complete title and ordered task snapshot. A later eligible mention also promotes
  still-hidden active Work and claims one create from its latest complete desired
  snapshot. Visibility is monotonic; concurrent progress updates are re-read and
  re-rendered through a bounded CAS loop, so promotion cannot leave visible Work
  without its latest Tracker claim.
- Finishing requires a final reply. Reply effects are attempted first; only
  `delivered` results permit `chat.delete` for the Tracker. Failed, unknown, or
  not-attempted replies leave deletion `not_attempted`.
- A later work cycle creates a new Tracker rather than reusing the deleted cycle's
  provider identity.
- Discord creates one joined-presence control and, for a visible cycle, an initial
  compact Channel Work Embed containing `◉ Agent is checking your message` from the
  same accepted binding transaction. Hidden cycles omit the Embed until promoted. A
  Scheduled Task-owned Tracker instead contains
  `◉ Agent is running a scheduled task…` followed by the task title on the next line.
  A state-only conversational progress change with unchanged tasks updates the current
  Tracker host in place, or creates one notification-suppressed standalone Tracker
  when none exists.
  A message-only Action delivers the reply without changing Tracker presentation.
  When an explicitly supplied ordered task snapshot differs from the canonical
  pre-transition tasks, every reply part is attempted first and Tracker relocation
  then removes the previous host: standalone hosts are deleted, while reply hosts keep
  their conversational content and have only Tracker Embeds and controls cleared.
  Confirmed removal permits notification-suppressed standalone creation with the
  complete latest Tracker. Creation is not gated on reply delivery. An identical task
  replacement or title-only progress change updates the current standalone or reply
  host in place. The normal successful relocation path therefore exposes at most one
  Tracker, while temporary absence is allowed between removal and creation. Creation
  and update both send a `View session` link derived from the current canonical
  Workspace, Agent, and Session target. Conversational Tracker creation and update
  also derive one signed `Conversation settings` action from the current Binding.
  Scheduled Task Trackers retain only Session navigation and task controls and keep
  their existing standalone notification behavior.
- Slack and Discord create no separate settings-only follow-up control. Every visible
  conversational Tracker is the recurring signed settings entry point. Initial hidden
  checking Work creates neither Tracker nor settings surface; canonical unfinished Todo
  publication or an eligible explicit invocation promotes the Tracker.
- A first eligible mention with no participation setting creates the setup claim and
  one immediate setup-control plan before Session or AgentRun creation. Slack opens the authenticated
  parent-scoped location selector. Discord posts `Answer in this channel` and
  `Answer in threads` directly in the parent channel and never provisions a thread
  until a valid selection commits.

The work cycle stores its title, complete provider-neutral version-2 desired
snapshot, desired revision, retained provider identity, and whether each Tracker part
is hosted by a standalone message or a conversational reply. Every progress effect is
revalidated against its exact desired revision before provider I/O; a newer canonical
snapshot makes an older pending progress effect not attempted. For changed Discord
tasks, process-local effect dependencies require confirmed previous-host removal before
silent standalone Tracker creation when a current host exists; otherwise creation
proceeds directly. Reply delivery does not gate relocation. Failed or
ambiguous Tracker mutations never roll back
canonical Work or a delivered reply, create no durable retry work, and converge only
through a later explicit complete progress update. A matching Slack deletion event or
confirmed `message_not_found` result clears the corresponding standalone identity. A
Tracker delete that returns `message_not_found` is treated as already absent.

## Approval Control Messages

Slack authorization control messages use Block Kit with a URL button and accessible
fallback text; they do not expose an approval URL as ordinary body text. Provider
participant labels and IDs are rendered in Slack plain-text objects so untrusted
mrkdwn cannot create mentions, links, or formatting.

Discord authorization controls use the same immediate `CONTROL_MESSAGE` effect and
Discord operation-key nonce fence as ordinary text output. They contain a bounded
approval explanation with a labelled Markdown review link, never a bare URL. Discord
request-local control payloads contain only the provider target, authenticated
approval link, and bounded text; durable access state retains no interaction token,
credential, raw event, attachment URL, or provider body.

Slack API validation responses for approval controls are confirmed
`failed/provider_rejected` outcomes. Only transport or server ambiguity is
`unknown/provider_ambiguous`.

Before access-control creation, the access request claims its owner-local control
projection as `unknown`. This conservative preclaim prevents a duplicate callback from
creating another control while provider I/O is in flight. A delivered create stores
only the current provider message key and `present` state on the access request;
confirmed failure or ambiguity stores only the current projection status.

Every compatible final approval decision returns one direct delete plan when the
access request has a current provider message key. The decision commits before the
caller attempts that delete. Deny and block use the access request's route and do not
require a Session binding. Delete success clears the key; failure or ambiguity updates
only current access projection state, does not change the final decision, and creates
no retry or reconciliation work.

The Activity Tracker identity and current projection status are Work-owned management
data.
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
Channel Work state. Intentionally hidden Work with no projection part reports `none`
rather than `missing`; its canonical desired progress remains readable.

## Slack Work Presence

Every ready active Slack conversational Work requests provider-native presence
regardless of Tracker visibility. Awaiting Work retains its Tracker and active
lifecycle but projects idle presence. A dedicated Gateway manager claims one
independent lease per active Slack connection, decrypts only that connection's current
Bot credential, and fences target projection and renewal by the captured configuration
generation.

Parent-channel Work uses public `assistant_threads_setStatus` at the first trigger
message retained for the cycle, with a bounded checking or work title and periodic
refresh before provider expiry. Exact-thread Work uses public
`agents_sessions_setStatus` at the retained root: active Work sends `processing` with
the first initiating participant, while finished or unavailable Work restores
`active`. These coordinates are presentation metadata only and never change Resource,
Binding, Session, history, or reply targeting.

The manager compares canonical targets with process-local delivered observations,
retries failed or ambiguous mutations only on later reconciliation, clears removed
active observations, and applies retained finished idle state once after ownership
handover. Lease loss, configuration replacement, disconnect, or shutdown stops the
owned loop; a graceful current owner best-effort clears observed active state before
release. Provider outcomes are sanitized and never mutate Work, connection health,
Tracker state, or reply delivery.

## Discord Typing Presence

Every ready active Discord conversational Work requests typing regardless of Tracker
visibility; awaiting Work is excluded until same-binding input or `continue` resumes
it. The current lease-fenced Discord Gateway owner derives distinct exact delivery
channels from PostgreSQL Binding, Resource, Session, Agent, route, connection,
App-claim, lease, and Work authority. It uses the existing long-lived
`discord.Client`, public `get_partial_messageable()`, and awaitable public `typing()`
operation to maintain one renewal task per Bot/channel.

Ready and Resume reconcile immediately and then periodically before the provider's
ten-second indicator expiry. Several Work cycles targeting one channel share one task
until the final cycle finishes. Target removal, `finish`, `ignore`, binding
termination, disconnect, lease loss, Client close, and process shutdown cancel and
await renewal tasks. Gateway restart reloads still-active targets; Work finished while
the Gateway is unavailable is not restored.

Discord exposes no explicit stop operation, so the final indicator may remain until
provider expiry after renewal stops. HTTP or OS failures are sanitized, retried at a
bounded presentation cadence, and never become Work, connection-health, delivery,
retry, or recovery authority.

## Continuation

A successfully completed run with ready unfinished Channel Work remains eligible for
idle continuation. Continuation is binding-aware, includes only ready binding handles,
and keeps awaiting Work in the compaction snapshot with an `Awaiting participant input`
indicator. A newly created canonical human mailbox item through the same binding clears
awaiting state and advances `state_revision` before the response Run becomes idle.
`continue` performs the same invalidation even when it only sends a message. Duplicate,
failed, provisioning-only, another-binding, Goal, Scheduled Task, and other Run sources
do not resume awaiting Work. Completing or clearing tasks, explicitly finishing with no
follow-up work, or `ignore` stops continuation for that binding. Other ready connected
bindings and independent continuation sources remain eligible.

## Lifecycle Cleanup Controls

Every binding termination other than Session archive captures one leave-presence plan
in addition to any required Tracker-delete plans. Slack renders `Agent name left this
conversation.` in Block Kit and Discord renders the same statement in an Embed; both
retain the `View session` button. Manual binding disconnect, route or connection
termination, and Agent decommission use this presentation. Session archive
terminalizes the binding and performs required Tracker cleanup without publishing a
leave-presence control. Lifecycle transactions never call a provider directly. When
terminal connection cleanup purges provider credentials, the service captures the
delivery target in memory before the purge. Post-commit execution revalidates the
durable connection, route, resource, binding, Session, and terminal state before
using that captured target. The captured credential and plans remain process-local.
Other cleanup paths resolve current credentials normally. Each captured plan is
attempted at most once; failure, ambiguity, cancellation, or process termination does
not roll back the terminal lifecycle transition and creates no recovery work.

## Scheduled Task Presentation

Scheduled Task provider effects use the same immediate process-local execution
boundary as other External Channel effects but have Scheduled-owned state.

- Task creation commits before one registration message is attempted. Slack uses
  native Edit and confirmed Cancel controls. Discord resolves an exact
  authorization-derived Session and Task Web edit URL at delivery time and pairs
  it with a signed Cancel control. The first Discord Cancel interaction
  reauthorizes the exact Task and Binding and returns an ephemeral confirmation;
  only its separately signed confirmation reauthorizes and executes the mutation.
  Both providers show the Task title prominently, use a human-readable schedule
  and next-run label as the primary presentation, and retain canonical cron or UTC
  schedule text only as secondary detail.
- Run start may create one Scheduled Activity Tracker.
- Scheduled-bound `channel_action continue` may publish a reply and replace the
  current progress title and ordered task list for the exact Binding.
- Scheduled-bound Channel Actions reject `request_input`; Scheduled Task lifecycle
  remains owned by `continue` and `submit_scheduled_task_result`.
- `submit_scheduled_task_result` may attach the same validated Runtime or Exchange
  file sources as `channel_action`. The terminal reply and files use the active
  cycle's exact Binding and conversation; the Agent does not choose another
  provider channel. Session-only cycles cannot publish terminal files.
- Terminal publication starts only after the canonical Session
  `scheduled_task_result` commits.
- Slack thread terminal replies use broadcast for parent surfacing. Discord
  thread terminal parts are forwarded to the parent channel in order.

Each effect is attempted once. Failure, ambiguity, cancellation, process loss, or
revoked authority is returned as a sanitized outcome and creates no retry,
outbox, compensation, canonical rollback, or fallback target. Recovery of an
already-committed terminal result does not replay provider publication.

## Changelog

- **2026-09-07** (spec_version 56) — Made changed complete task snapshots relocate
  Discord Trackers through current-host removal and silent standalone creation,
  retained current host position for unchanged tasks, and removed final-reply identity
  attachment from process-local effects.
- **2026-09-05** (spec_version 55) — Moved Discord conversational Trackers to
  messages that accompany changed progress: replies deliver first, the previous
  standalone or reply-hosted Tracker is removed, and a partial edit attaches the
  complete Tracker to the final reply. Added persisted host classification,
  same-Binding Action serialization, process-local effect dependencies,
  notification-suppressed standalone creation, exact progress-revision revalidation,
  and best-effort later-update recovery.
- **2026-08-31** (spec_version 54) — Added concise `request_input` guidance,
  delivery-confirmed binding-scoped awaiting state, same-binding human-input and
  `continue` resume, ready-only idle continuation, awaiting compaction, Slack idle
  presence, Discord typing suspension, and the version-4 Channel Work migration.
- **2026-08-29** (spec_version 53) — Added leased Slack channel/thread Work presence,
  aligned Slack Tracker visibility and promotion with Discord, moved recurring
  conversation settings onto visible Slack Trackers, and removed settings-only
  follow-up controls without changing Scheduled Task actions or reply targeting.
- **2026-08-29** (spec_version 52) — Made unfinished Todo publication promote hidden
  Discord Work and create its current Tracker, while preserving hidden initial
  checking, one Tracker identity, typing, Slack, and Scheduled Task behavior.
- **2026-08-29** (spec_version 51) — Added the existing signed Binding settings action
  to every visible conversational Discord Tracker create/update, removed the separate
  Discord follow-up settings-only control, and preserved Slack, joined presence,
  hidden Work, and Scheduled Task presentation.
- **2026-08-28** (spec_version 50) — Made Discord conversational Trackers
  mention-gated per Work cycle, retained hidden canonical progress, and added
  lease-fenced public-SDK typing for every active Discord conversational Work.
- **2026-08-20** (spec_version 48) — Made new Discord Thread creation use the
  connection-owned four-value automatic archive policy while leaving existing and
  reconciled Threads unchanged.
- **2026-08-17** (spec_version 47) — Replaced Discord Scheduled Task native edit
  controls with exact Session Web editor links and added provider-authorized
  ephemeral cancellation confirmation; Slack and Web destructive copy now use
  Cancel terminology.

- **2026-08-17** (spec_version 46) — Added Scheduled terminal file delivery through
  the exact current Binding with the same outbound file validation and Runtime
  transfer context as `channel_action`.

- **2026-08-17** (spec_version 45) — Made Slack and Discord Scheduled Task
  registration messages title-first with human-readable schedule and next-run
  labels while retaining canonical schedule detail and signed controls.

- **2026-08-16** (spec_version 44) — Added commit-first Scheduled registration,
  progress, exact-thread terminal presentation, and explicit no-replay behavior.

- **2026-08-11** (spec_version 42) — Made silent `ignore` completion delete the
  selected binding's current Slack or Discord Activity Tracker without a final reply,
  while retaining `finish` cleanup gating on delivered final replies.
- **2026-08-11** (spec_version 41) — Reused one authenticated pinned `discord.py`
  session across each multi-operation Discord delivery effect and moved supported
  text, thread, message, history, and attachment operations to the isolated private
  HTTP adapter without changing one-attempt, nonce, validation, or ambiguity
  semantics.
- **2026-08-11** (spec_version 40) — Kept authorized `exchange://` Channel
  publication available without a managed Runtime while retaining Runtime storage
  admission for absolute Runtime paths and mixed-source calls.
- **2026-08-09** (spec_version 39) — Exposed `ignore` on every model input boundary,
  removed continuation binding scope, and made silent active-Work completion
  independent of recorded task status.
- **2026-08-05** (spec_version 38) — Suppressed the provider leave-presence
  control when Session archive terminalizes a binding, while retaining the terminal
  transition and Activity Tracker cleanup.
- **2026-08-04** (spec_version 37) — Added continuation-only `ignore`, with
  tool-follow-up scope retention, atomic unfinished-task rejection, and zero provider
  effects.
- **2026-08-04** (spec_version 36) — Removed provider-delivery capability gating. The required service now resolves Runtime readiness only during file-bearing Tool execution.
- **2026-08-03** (spec_version 35) — Made binding-specific Session-bound Toolkit
  State the sole Channel Work and current provider-projection authority while
  preserving commit-before-I/O delivery and cycle/revision settlement fences.
- **2026-08-03** (spec_version 34) — Added the Run-local adjacent-turn verbosity
  guard for repeated `channel_action` calls with the same binding and mode.
- **2026-08-03** (spec_version 33) — Added canonical `View session` controls to
  initial and updated Slack and Discord Activity Trackers.
- **2026-08-03** (spec_version 32) — Retained exact provisional-title evidence only
  for direct Discord thread creation and added one post-title-commit GET plus
  conditional name-only PATCH with no retry or delivery-attempt ledger.
- **2026-08-02** (spec_version 31) — Replaced durable Channel Action, delivery
  attempt, Worker recovery, and lifecycle intent authority with ordinary Tool
  call/result history, immediate ordered effects, owner-local current projection, and
  process-local post-commit controls.
- **2026-08-02** (spec_version 29) — Added direct parent-channel targeting, versioned
  conversation-settings presence actions, and bounded existing-Binding control
  reconciliation without history rewrite.
- **2026-08-01** (spec_version 28) — Replaced the button-only Session link with
  joined-presence controls and added one leave-presence control to every binding
  termination path, including post-purge delivery through an in-memory captured
  target that retains the same durable one-attempt fence.
- **2026-08-01** (spec_version 27) — Decoupled initial Session-link and progress
  provider-control outcomes from canonical mailbox promotion, Session wake, and
  AgentRun creation.
- **2026-07-31** (spec_version 25) — Required durable Session-link and initial
  progress intents, removed transient ingress health from outbound REST authority,
  and derived new Discord thread titles from the routed Agent name.
- **2026-07-31** (spec_version 24) — Replaced the file key in place with direct
  provider coordinates and removed Session-event source lookup and legacy key fallback.
- **2026-07-30** (spec_version 22) — Added Worker-owned bounded provider-control
  recovery and clarified the claim, provider-I/O, and final-settlement split with
  same-attempt authority revalidation.
- **2026-07-29** (spec_version 21) — Moved Discord's retained functional Channel Work
  Tracker from ordinary message text into one bounded Embed while preserving its
  durable create, update, replacement, recovery, and cleanup lifecycle.
- **2026-07-28** (spec_version 20) — Replaced Discord's multi-page Embed Activity
  Tracker with one bounded retained text message that keeps every ordered task visible,
  prioritizes useful task context and sources, and clears legacy Embed cards.
- **2026-07-28** (spec_version 19) — Limited visible Slack and Discord Agent-name prefixes to multi-app connections; single-app delivery now relies on the dedicated App identity.
- **2026-07-28** (spec_version 18) — Replaced dynamic Channel Work prompt injection with a minimal capability-aware static publication boundary, deferred Channel tools through Tool Search, and kept only unfinished-work continuity in compaction.

- **2026-07-28** (spec_version 17) — Promoted the completed Runtime File Transfer
  cutover for file-bearing replies: every Runtime source uses a verified-object
  consumer claim and bounded provider stream, failures before mutation fail closed,
  and provider mutation is never replayed after start or ambiguity.
- **2026-07-28** (spec_version 16) — Added reconciliation-fenced Discord initial
  Session/work delivery and persisted root-thread targeting for all later output.
- **2026-07-26** (spec_version 15) — Added nonce-fenced Discord approval-control
  creation and provider-aware post-decision control deletion through the normal
  delivery ledger.
- **2026-07-26** (spec_version 14) — Added nonce-fenced Discord message and
  multipart delivery, ordered bounded progress pages, and conservative
  classification of rate-limit, rejection, and ambiguous provider outcomes.
- **2026-07-26** (spec_version 13) — Added the required bold Agent-name prefix for
  Agent-associated Slack output and capability-aware icon override with safe fallback.
- **2026-07-26** (spec_version 14) — Replaced Runtime `FileStorage` range-read relay with
  capability-gated verified-object provider streaming, one Runtime upload per source, batch-held
  claims, post-provider acknowledgement/settlement, and fail-closed pre-cutover wiring.
- **2026-07-26** (spec_version 13) — Added the required bold Agent-name prefix for
  Agent-associated Slack output and capability-aware icon override with safe fallback.
- **2026-07-25** (spec_version 12) — Added authority-resolved `exchange://` outbound
  sources, explicit source-kind manifests, post-commit Exchange revalidation, supported
  source guidance, and form-encoded Slack external-upload completion.
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
