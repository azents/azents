---
title: "External Channel Lifecycle"
created: 2026-07-22
tags: [backend, external-channel, lifecycle, session, agent, discord]
spec_type: flow
owner: "@Hardtack"
touches_domains: [external-channel, agent, conversation]
code_paths:
  - python/apps/azents/src/azents/core/external_channel_session_presence.py
  - python/apps/azents/src/azents/core/session_lifecycle.py
  - python/apps/azents/src/azents/repos/external_channel/lifecycle.py
  - python/apps/azents/src/azents/repos/external_channel/work_state.py
  - python/apps/azents/src/azents/services/external_channel/lifecycle.py
  - python/apps/azents/src/azents/services/external_channel/file_transfer.py
  - python/apps/azents/src/azents/services/external_channel/management.py
  - python/apps/azents/src/azents/services/external_channel/discord_activation.py
  - python/apps/azents/src/azents/services/external_channel/discord_api.py
  - python/apps/azents/src/azents/services/external_channel/discord_endpoint.py
  - python/apps/azents/src/azents/services/external_channel/discord_gateway.py
  - python/apps/azents/src/azents/services/external_channel/discord_gateway_manager.py
  - python/apps/azents/src/azents/services/external_channel/slack_sdk_client.py
  - python/apps/azents/src/azents/services/external_channel/slack_presence_manager.py
  - python/apps/azents/src/azents/services/external_channel/slack_socket.py
  - python/apps/azents/src/azents/services/external_channel/socket_manager.py
  - python/apps/azents/src/azents/services/external_channel/gateway_runtime.py
  - python/apps/azents/src/cli/externalchannelgateway.py
  - python/apps/azents/src/azents/worker/worker.py
  - python/apps/azents/src/azents/api/public/external_channel/v1/management_route.py
  - python/apps/azents/src/azents/services/external_channel/access.py
  - python/apps/azents/src/azents/services/session_lifecycle/orchestrator.py
  - python/apps/azents/src/azents/services/session_lifecycle/registry.py
  - python/apps/azents/src/azents/services/archived_session_purge.py
  - python/apps/azents/src/azents/services/agent_decommission.py
  - python/apps/azents/src/azents/repos/agent_decommission_finalizer/**
  - python/apps/azents/src/azents/repos/session_lifecycle_finalizer/**
  - typescript/apps/azents-web/src/features/external-channel-management/**
  - typescript/apps/azents-web/src/features/session-channels/**
last_verified_at: 2026-09-01
spec_version: 41
---

# External Channel Lifecycle

## Direct Management Transitions

Disconnecting a connected binding terminally sets `disconnected_at`, ends active
Channel Work, and captures one leave-presence plan plus Activity Tracker cleanup plans
when needed. Slack renders the presence control with Block Kit and Discord
uses an Embed; both include the current Agent name and one `View session` button.
The next Discord Gateway typing reconciliation removes the binding's delivery channel
unless another active Work cycle for the same Bot/channel still contributes it.
Provider conversation positions and already projected AgentSession history remain.
The timestamp is the only binding connectedness authority; no lifecycle path clears
it or reactivates history. Repeating a manual binding disconnect does not create a
second leave-presence control.

Disconnecting a parent Binding does not clear its active participation setting. A later
eligible explicit top-level mention may create a new parent Binding according to that
setting. Changing location uses the provider-native settings transition instead:
Channel-to-Threads bumps the setting generation and disconnects only the parent
Binding; Threads-to-Channel updates the setting but creates no empty Session, leaving
parent Binding creation to the next eligible explicit mention.

Replacing a connected binding's concrete response mode preserves its binding,
Session, work, provider projection, and conversation-position lifecycle state. The management
boundary scopes the mutation to the requested Workspace, Agent, Session, and connected
binding. A parent Binding replacement updates the active participation setting and
Binding atomically; a thread replacement updates only that Binding. Once
`disconnected_at` is set, the retained final mode is read-only and the
same mutation returns the not-found-shaped management result.

`channel_action ignore` is not a binding lifecycle transition. It silently finishes
only the current active Channel Work cycle, leaves the binding connected, and creates
no leave-presence or Activity Tracker cleanup plan. Recorded task status does not block
the transition, and the finished cycle no longer participates in idle continuation or
Slack Work presence or Discord typing renewal.

Disconnecting a connection accepts every lifecycle and credential state. It
terminalizes the connection, terminates owned active resources/bindings/work, commits
one leave-presence plan for each newly disconnected binding, clears credentials,
and commits terminal local state before provider cleanup runs. Provider targets are
captured in memory before route detachment or credential purge. Post-commit execution
revalidates the durable connection, route, resource, binding, Session, terminal
binding state, and purged connection state before using that captured target.
Credentials and plans are not copied into another persistence surface. Repeating the
command is safe and returns no duplicate cleanup plan.
Disconnected connection rows remain durable history roots but are excluded from the
active Single management list. Disconnected Multi Apps remain readable through
Workspace history but reject mutation.

Removing the sole Single App association disconnects the entire App. Removing one
Multi App route generation-fences the connection, marks only that catalog route
removed, disconnects bindings owned by that route, and invalidates its active channel
defaults, participation settings, and pending setup claims. It preserves the connection
and every other route. A removed Multi route
can be explicitly re-enabled only while the connection is mutable and Multi growth is
rollout-enabled; detached historical Agent snapshots never become routable.

Replacing or clearing a Multi channel default is generation-fenced. It invalidates the
old participation setting and pending setup claim, terminally disconnects only the old
connected parent Binding with its process-local provider cleanup plans, and preserves every thread
Resource, Binding, Session, and concrete mode. The replacement route starts without a
participation setting; a later eligible top-level mention begins setup. Stale impact
previews fail with conflict instead of applying a destructive mutation against newer
state.

Editing a visible Slack connection replaces App ID, HTTP/Socket transport, and the
complete submitted credential set in one operation. It clears stale provider
identity, capability, health, Socket lease, Work presence lease, and gap projections,
increments the configuration generation, and immediately validates the replacement
configuration. No lifecycle status prevents editing a visible connection, and no
transport fallback occurs.

Editing a visible Discord connection replaces the submitted Application identity,
target Guild configuration, and complete Bot credential set in one fenced operation.
It invalidates stale callback selector, Application claim, Gateway lease/checkpoint,
gap, identity, capability, and health projections before callback activation repeats.
Each activation attempt opens one authenticated pinned `discord.py` Client session and
reuses it for current Application metadata, Bot identity, and Guild command
reconciliation, then closes it before the activation attempt returns.
Callback activation first persists the new selector hash and Discord Application public
key under the unchanged credential and configuration-generation fences, commits that
provisional PING-only authority, then asks Discord to register the endpoint. A failed
registration, a successful response that does not report the exact requested
endpoint, or a required Guild-scoped `Ask an Azents Agent` Message Command failure
clears that provisional authority and moves the connection to `reconnect_required`;
normal interactions are rejected until the final activation commit. The External
Channel Gateway's Discord manager can claim only the newly activated configuration;
a stale manager cannot continue mutation after replacement or disconnect. Endpoint
registration uses the narrow Bot-authenticated
current-Application direct-transport gap because the adopted public `discord.py`
implementation cannot transmit the endpoint field. The gap is removed when that SDK
capability becomes usable. Registration does not require the user to copy the opaque
per-connection callback into Discord Developer Portal.
Retrying a `reconnect_required` Discord connection restores `configuring` while it
persists a new provisional selector and public key, so endpoint-verification PING can
authenticate without admitting normal interactions.

A completed Discord disconnect releases its current Application claim. During
activation, a claim held only by a disconnected history row transfers atomically to
the new connection; claims held by a mutable connection remain exclusive. Failed
Discord activation writes one sanitized, structured operator log with the operation,
connection identifier when available, failure stage, stable failure code, and error
class. It never serializes credentials, callback selectors or URLs, request headers,
raw provider responses, or exception text.

Discord setup persists its connection and Single App route before activation. An
activation failure returns the created connection rather than a failed setup request,
so retrying the dialog cannot create duplicate rows. The connection transitions to
`reconnect_required` and stores only a controlled `last_health_code`, cleared by
successful activation or configuration replacement. Agent Settings renders the code
as a localized cause and recovery action; it never renders provider response text.

Revoking a participant grant deletes the selected grant policy row after an ownership
check. It does not delete canonical provider content, invocation history, projected
Session events, or unrelated grants.

An Allow decision locks and revalidates the connection, route, Resource, optional
setup claim, Binding, and request. Setup-linked Allow creates the grant and returns the
claim to location setup without creating Session-owned state. Legacy configured-thread
Allow may create or reuse its connected Binding and, after its authorization
transaction commits, replays the immutable conversation-position boundary through
shared synchronous ingestion. Selected setup instead replays only after a valid
location choice. Either canonical acceptance
atomically creates or reuses the real Session, work projection, deterministic canonical
mailbox input, conversation-position advance, Session running state, recoverable
wake-up identity, and Session navigation/progress plans. Provider controls run once
after commit and remain independent from execution. Repeated Allow decisions reuse the
same durable binding and mailbox identities. Final Allow, Deny, and Block decisions
return one direct delete plan when their approval control has a current provider
identity.

Every new file download and file-bearing publication revalidates the current Agent,
Session, route, binding, connection, and directional capability. Binding disconnect,
connection disconnect, Session archive, and Agent decommission therefore prevent new
transfers immediately through the existing lifecycle fences. A provider access change or
file deletion is observed at download time. An in-progress outbound provider attempt
continues only within its current Tool execution and is never replayed after a
lifecycle change.

Provider credential and permission failures move only connection health to
`reconnect_required`; they preserve route relationships, bindings, and work.
Authenticated Slack token revocation follows that recoverable health transition.
Authenticated Slack App uninstall instead terminally disconnects the connection,
creates leave-presence and Tracker cleanup only for bindings that were still
connected, removes active route authority, marks resources unavailable, and clears
provider identity and credentials. Cleanup targets are captured before the purge and
attempted after the terminal commit. A repeated uninstall is idempotent and creates
no duplicate presence control. In-flight validation
results are generation-fenced so they cannot overwrite a newer edit or disconnect.
Transient `degraded` or `reconnect_required` ingress health does not disconnect a
binding or block an otherwise authorized outbound REST delivery. Terminal connection
disconnect still clears credentials and sets binding terminal timestamps.

Discord Gateway credential and non-reconnectable intent or close-code failures
atomically record the fenced gap, release the current Gateway lease, and move only
connection health to `reconnect_required`; they preserve route relationships,
bindings, and work. During login, the public SDK Application metadata must report an
Interaction Endpoint with the configured callback origin and path and a selector whose
hash matches the active connection. An absent or mismatched endpoint records
`interaction_endpoint_drift` through the same terminal lease fence without retaining
the raw selector. During SDK-owned recovery, `disconnect` records a fenced degraded
gap and `ready` or `resumed` marks the same lease active and clears the gap. Azents
does not run a second Gateway reconnect or Resume loop. A one-minute continuous
unready deadline preserves brief SDK-owned Resume but cancels and discards a client
that remains unavailable, records a fenced degraded gap, releases its lease, and lets
the connection be reclaimed with a fresh client. The current Gateway owner also
reconciles process-local typing tasks from ready active Work under the same lease and
generation fences. Awaiting Work is excluded. A restart or Resume restores still-ready
targets; Work finished or awaiting during the gap is absent. Typing provider failure
does not change connection health.

Slack Socket Mode keeps one SDK lifecycle per current fenced lease. SDK endpoint
replacement records a degraded gap, successful establishment marks active, and
terminal App-token rejection moves only connection health to `reconnect_required`.
Recoverable endpoint, close, refresh, and stale-session transitions remain inside the
SDK lifecycle. Lease loss or shutdown closes the SDK client before authority is
released.

One provider-neutral External Channel Gateway process supervises both persistent
transport managers. General Agent Worker rollout, scaling, and broker consumption do
not change Slack Socket or Discord Gateway ownership. A customer-specific terminal
connection remains isolated durable health; unexpected completion of either required
top-level manager stops the gateway process so Kubernetes cannot keep a partially
supervised gateway ready.

Discord callback and Gateway authority are released during disconnect after terminal
local state commits; provider cleanup failure does not roll back the disconnect and
creates no recovery work.

## Session Archive and Restore

External Channel is registered as the `session.external-channel` lifecycle participant.

Archive uses the explicit terminal transition policy inside the caller-owned archive transaction:

1. lock connected bindings in the Session subtree;
2. set their terminal disconnect timestamps and preserve their history;
3. end each binding's Channel Work in its Session-bound Toolkit State;
4. preserve already projected Session history and normal mailbox lifecycle state; and
5. capture cleanup plans for retained Activity Trackers without creating a
   leave-presence plan.

Provider presence and cleanup effects run once after commit. Failure, ambiguity, or
interruption does not roll back Session archive and creates no recovery work. Finished
archived Work disappears from the next Discord typing target projection; no explicit
provider stop mutation exists.
External Channel file transfer adds no stored byte object or file-specific cleanup
participant.

Restore uses `preserve`. It validates that terminal bindings, ended work, and cleanup
bookkeeping remain terminal. Restore never reactivates External Channel state;
managers must establish new provider state explicitly.

## Permanent Session Purge

Newly fenced jobs include the participant in their immutable purge snapshot. Jobs
that were already fenced before the participant was registered retain their
earlier snapshot and do not retroactively add or execute it. Restrictive
AgentSession ownership still prevents finalization if Session-owned External
Channel roots exist outside that earlier snapshot.

- **Prepare** validates the terminal owner-local state without provider execution.
- **Cleanup** deletes access decisions tied directly to the Session, binding-specific
  External Channel Work Toolkit State values, and bindings in restrictive ownership
  order.
- **Verify/finalize** rejects AgentSession tree finalization while actionable bindings
  or binding-specific Work Toolkit State remain. Generic Session ownership remains
  the final database cascade boundary for any other Toolkit State.

Connection, route, resource, conversation-position, principal, interaction,
Agent-scoped grant, and block roots are not cascade-deleted through AgentSession.

## Agent Decommission

Agent deletion is asynchronous and irreversible. Its lifecycle status fences new
routing and invocation, then decommission archives/terminalizes owned Session state
through the normal lifecycle participant and commits leave-presence and Tracker
cleanup plans. A Single App route removal disconnects that App; a Multi App route
removal preserves the Workspace-owned App and its other Agents. Historical routes
retain the immutable Agent snapshot with no routable Agent ID. The finalizer never
bypasses restrictive ownership boundaries.

## Operational Projection

Agent Settings shows active Single App health, reconnect requirement with a
localized safe Discord cause and recovery action, revocation, transport, complete
connection editing, unconditional disconnect, complete provider user IDs for grants
and blocks, and associated Multi Apps as read-only Workspace-managed context.
Workspace integrations owns Multi App setup, catalog, channel defaults, impact
previews including participation-setting invalidation and parent-Binding disconnect,
and terminal disconnect. Destructive connection, route, default, grant, and block
actions use in-product confirmation dialogs.

Session Channels remains readable after archive and displays disconnected bindings,
ended work, ordered task state, and the Activity Tracker projection state. Binding
disconnect also uses an in-product confirmation
dialog. Restore controls do not imply provider reactivation.

## Scheduled Task Cleanup

Binding disconnect, route removal, connection removal, and App uninstall delete
Scheduled Task definitions and pre-start trigger/admitted-cycle state that target
the affected Binding. A cycle that already crossed the start-admission boundary
remains valid Session work, but the disconnected Binding no longer authorizes
progress, registration, or terminal provider effects.

Session archive removes every Task and pre-start Scheduled input in the archived
tree. It may preserve active Runs only when each running Session is executing a
started Scheduled cycle; unrelated active work still blocks archive. Restore does
not recreate removed scheduling authority. Permanent purge waits for preserved
started cycles, removes residual Task/trigger/cycle state, and verifies absence
before finalization.

## Changelog

- **2026-09-01** (spec_version 41) — Preserved brief SDK-owned Discord Resume while
  replacing a continuously unready client after one minute, and excluded awaiting
  Work from lifecycle-restored typing targets.
- **2026-08-29** (spec_version 40) — Added Slack Work presence lease reset to
  configuration replacement and terminal connection cleanup, and excluded finished
  Work from both Slack presence and Discord typing renewal.
- **2026-08-28** (spec_version 39) — Added lifecycle removal and restart recovery
  rules for lease-fenced Discord typing targets without introducing durable typing
  state or provider stop operations.
- **2026-08-25** (spec_version 38) — Required Discord activation to confirm the
  provider-reported Interaction Endpoint postcondition and made Gateway login
  terminalize absent or mismatched endpoint authority as reconnect-required.
- **2026-08-16** (spec_version 37) — Added Scheduled Task Binding termination,
  Session archive/restore, started-cycle preservation, and purge absence rules.

- **2026-08-11** (spec_version 36) — Reused one authenticated pinned `discord.py`
  Client session across Discord activation metadata and command reconciliation while
  preserving configuration fencing, activation deadlines, and the existing direct
  endpoint and command-create gaps.
- **2026-08-09** (spec_version 35) — Classified automatic Discord Interaction
  Endpoint registration as a removable direct-transport gap while the adopted public
  SDK cannot transmit the endpoint field.
- **2026-08-09** (spec_version 34) — Removed continuation-only and unfinished-task
  restrictions from silent Work completion while preserving binding lifecycle and
  provider-cleanup boundaries.
- **2026-08-09** (spec_version 33) — Corrected automatic Discord Interaction Endpoint
  registration to edit the Bot-authenticated current Application and clarified that
  users do not manually copy opaque callback URLs into Discord Developer Portal.
- **2026-08-05** (spec_version 32) — Kept Session archive binding termination and
  Activity Tracker cleanup while suppressing the provider leave-presence control.
- **2026-08-03** (spec_version 31) — Clarified that eligible silent Work completion
  leaves the binding lifecycle unchanged and produces no lifecycle cleanup plan.
- **2026-08-03** (spec_version 30) — Moved Channel Work archive, restore, purge, and
  verification to binding-specific Session-bound Toolkit State and removed the
  dedicated Work table from lifecycle roots and Agent finalization.
- **2026-08-02** (spec_version 29) — Replaced lifecycle delivery intents and
  bookkeeping with bounded process-local post-commit plans while retaining terminal
  canonical state and owner-local current projection.
- **2026-08-02** (spec_version 28) — Coupled parent location and selected-Agent
  transitions to participation-setting generations, setup-claim invalidation, and
  parent-only Binding terminalization while preserving thread conversations and
  allowing later parent-Binding recreation.
- **2026-08-01** (spec_version 27) — Added connected-only binding response-mode
  replacement as a lifecycle-preserving management transition and retained the final
  mode as read-only terminal history.
- **2026-08-01** (spec_version 26) — Added one durable leave-presence control to every
  binding termination path, including manual disconnect, route or connection removal,
  Session archive, Agent decommission, and authenticated App uninstall. Terminal
  connection paths capture delivery authority before credential purge and revalidate
  durable terminal identity after commit without persisting another credential copy.
- **2026-08-01** (spec_version 25) — Made the conversation position plus canonical
  mailbox own Allow replay acceptance and wake recovery while provider-control
  delivery remains independent.
- **2026-07-31** (spec_version 23) — Made binding disconnect a timestamp-only
  terminal boundary and separated outbound REST authority from transient persistent-
  ingress health.
- **2026-07-31** (spec_version 22) — Unified Slack Socket Mode and Discord Gateway
  lifecycle supervision in the provider-neutral External Channel Gateway and decoupled
  persistent connections from Agent Worker lifecycle.
- **2026-07-31** (spec_version 21) — Removed invocation-batch and provider-message
  lifecycle ownership; Session cleanup now covers retained External Channel roots while
  canonical mailbox and Session-event state follow their existing Session owners.
- **2026-07-31** (spec_version 20) — Made Slack and Discord typed SDK lifecycle
  callbacks the fenced connection-health authority while leaving recoverable
  connection mechanics inside each provider SDK.
- **2026-07-31** (spec_version 19) — Removed pending-context and waiting-hydration
  lifecycle state and made Allow replay synchronous through immutable conversation
  positions. The later `provider-260731` replacement removed accepted-batch ownership.
- **2026-07-28** (spec_version 18) — Replaced immediate Discord Allow activation
  with shared bounded hydration and reconciliation fences before initial work and wake.
- **2026-07-27** (spec_version 17) — Restored `configuring` provisional PING
  authority when retrying a Discord callback activation from `reconnect_required`.
- **2026-07-27** (spec_version 16) — Persisted controlled Discord activation
  failure codes, returned already-created setup connections after activation
  failures, and rendered localized durable recovery guidance.
- **2026-07-27** (spec_version 15) — Released Discord App claims during terminal
  disconnect and configuration replacement, reclaimed claims from disconnected
  history during activation, and made setup-failure diagnostics structured and
  secret-free.
- **2026-07-27** (spec_version 14) — Made terminal Discord Gateway failures
  atomically fence, release, and suppress further scheduler claims until reactivation.
- **2026-07-26** (spec_version 13) — Added provider-aware Allow activation:
  immediate Discord binding/work/invocation release and approval-control deletion,
  while preserving Slack hydration activation.
- **2026-07-26** (spec_version 12) — Defined Discord's provisional PING-only
  callback activation order, fenced cleanup after registration failure, and removal of
  the deployment-scoped Discord rollout gate.
- **2026-07-26** (spec_version 11) — Added fenced Discord credential/callback
  replacement, Gateway lease/checkpoint invalidation, and provider-health repair
  behavior without rerouting retained bindings.
- **2026-07-26** (spec_version 10) — Added mode-specific association removal,
  generation-fenced Multi route/default/App mutations, invalidated defaults,
  historical route snapshots, and read-only disconnected Multi Apps.
- **2026-07-23** (spec_version 9) — Applied existing binding, connection, Session, and
  Agent fences to every file transfer and clarified that transferred bytes add no
  retention or purge participant.
- **2026-07-23** (spec_version 8) — Made normal delivered-answer completion delete the transient Activity Tracker while retaining terminal lifecycle cleanup for any remaining provider identity.
- **2026-07-23** (spec_version 7) — Clarified that normal completion retains Activity Trackers while binding, connection, Session, and Agent lifecycle transitions own terminal provider deletion.
- **2026-07-23** (spec_version 6) — Added hard grant removal, complete access identities, in-product destructive confirmations, and task/progress lifecycle presentation.
- **2026-07-23** (spec_version 5) — Removed route lifecycle transitions. Connection status owns disconnect and provider health, while Agent lifecycle owns new-execution eligibility.
- **2026-07-22** (spec_version 4) — Kept provider health failures and App uninstall independent from Agent route lifecycle and fenced stale validation results.
- **2026-07-22** (spec_version 3) — Made connection disconnect unconditional and idempotent, committed terminal state before provider cleanup, omitted disconnected rows from active management, and replaced reconnect/transport actions with complete Slack configuration editing.
- **2026-07-22** (spec_version 2) — Preserved already-fenced participant snapshots across registry growth while retaining restrictive finalization safety.
- **2026-07-22** (spec_version 1) — Promoted terminal disconnect, archive/restore policy, restrictive purge ownership, post-commit cleanup, and Agent decommission behavior.
