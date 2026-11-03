---
title: "External Channel lifecycle"
created: 2026-07-22
tags: [backend, external-channel, lifecycle, session, agent, discord]
---

# External Channel lifecycle

Disconnect, archive, purge and Agent decommission effects across channel-owned resources.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [External Channels](../domain/external-channel.md)
- [Agent deletion](../domain/agent-deletion.md)
- [Conversations and events](../domain/conversation.md)
- [Session Routines](../domain/routine.md)

## Direct Management Transitions

Management services sequence completed, DB-only repository operations. The management
operation repository owns authorization reads, configuration and route writes,
generation checks, and terminal transitions; it returns detached projections or
provider-effect plans after the relevant session closes. Provider validation,
activation, terminal controls, and conversation/participation lease assertions execute
outside active database transactions. Single-connection disconnect retains two
separate durable stages: beginning DISCONNECTING, then completing lifecycle cleanup
and terminal state. A second-stage failure does not undo the first committed stage.
Provider terminal controls run only after both stages finish successfully.

User-originated Agent-owned management also follows the
[Agent deletion read-only boundary](../domain/agent-deletion.md#public-status-and-read-only-admission).
Single App configuration and Slack/Discord validation or activation derive ownership
from persisted mode/route state and acquire the active-Agent fence before child writes
and final publication. Shared Multi App configuration is not disabled by deletion of
one routed Agent. A Discord activation denied at final publication clears its exact
provisional callback before propagating the lifecycle conflict. Native disconnect,
Gateway reconciliation and deletion cleanup retain their explicit lifecycle authority.

Binding termination atomically clears that Binding's Session Primary reference.
Because archive locks Session before Binding while terminal management can already
hold Binding before clearing Primary, the completed Binding disconnect, Multi
route removal, Multi connection disconnect, both Single connection disconnect
stages, Multi channel-default replace/clear, parent participation-setting mutation
and provider revocation operations use the existing confirmed-transaction-abort
recovery boundary. A database-confirmed deadlock or serialization abort retries
only the complete DB-only owner operation after its scope closes. Unknown commit,
authority failure and cancellation do not replay; provider effects remain outside
this boundary. Single disconnect retains its earlier committed stage and cleanup
plans while retrying only the aborted second stage.

Disconnecting a connected binding terminally sets `disconnected_at`, ends active
Channel Work, and captures one leave-presence plan plus Activity Tracker cleanup plans
when needed. Discord cleanup deletes a standalone Tracker host but preserves a
conversational reply host by clearing only its Tracker Embed and controls. Slack
renders the presence control with Block Kit and Discord uses an Embed; both include the
current Agent name and one `View session` button.
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
state. Impact previews use ordinary connection/route/count reads, tolerate
committed lag, and never acquire destructive transition locks. The actual confirmed
mutation still validates its existing generation and exact lifecycle references.

Editing a visible Slack connection replaces App ID, HTTP/Socket transport, and the
complete submitted credential set in one operation. It clears stale provider
identity, capability, health, Socket lease, Work presence lease, and gap projections,
increments the configuration generation, and immediately validates the replacement
configuration. Single and Multi replacement serialize the actual configuration
generation transition and reject a connection already disconnecting or disconnected;
a stale replacement cannot resurrect it. No transport fallback occurs.

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
no duplicate presence control. The completed revocation repository operation applies
the required configuration generation and optional Socket lease owner predicates,
captures terminal cleanup targets, and purges provider state in one atomic scope.
A stale predicate leaves the connection unchanged; purge failure rolls back the
terminal transition. The service attempts captured cleanup only after commit and
scope exit. In-flight validation
results are generation-fenced so they cannot overwrite a newer edit or disconnect.
The connection service reads its Workspace-owned configuration through a completed
repository operation, performs provider validation with no active database
transaction, and returns its fenced health outcome through a second completed
repository operation. Transient `degraded` or `reconnect_required` ingress health does not disconnect a
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
reconciles process-local typing tasks from ready active Work whose bound Session is
running with a running AgentRun and no stop request, under the same lease and generation
fences. Awaiting Work is excluded. A restart or Resume restores only still-running
targets; Work finished, awaiting, or without running execution during the gap is absent.
Run termination or Session idle state removes typing without finishing retained Work.
Typing provider failure
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
Its DB-only participant operations live in repository composition, not in a service
that receives live Sessions. Archive/purge operations compose the narrower lifecycle
repository atomically with their root transition and participant state. The lifecycle
service only consumes detached committed provider cleanup plans; it owns no DB scope.
Scheduled participant persistence uses the same repository-only boundary.

Archive uses the explicit terminal transition policy inside the archive
repository's transaction. The concrete lifecycle operation composes participant
mutations and the root transition in registry order:

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

Installed lifecycle ownership diagnostics read the PostgreSQL foreign-key and
referential-trigger graph through the completed
`PostgreSQLSessionLifecycleGraphRepository` native read-only operation. Detached
graph contracts are defined in `core/session_lifecycle_schema.py`; the service
schema validator performs only pure ownership and reachable-delete-path checks
after the repository scope closes. This ownership boundary preserves existing
manifest classifications and complete violation paths and does not change purge
or parent-delete authority.

Newly fenced jobs include the participant in their immutable purge snapshot. Jobs
that were already fenced before the participant was registered retain their
earlier snapshot and do not retroactively add or execute it. Restrictive
AgentSession ownership still prevents finalization if Session-owned External
Channel roots exist outside that earlier snapshot.

- **Prepare** validates the terminal owner-local state without provider execution.
- **Cleanup** deletes access decisions tied directly to the Session, binding-specific
  External Channel Work Toolkit State values, actor-private external model drafts,
  and bindings in restrictive ownership order. Immutable model mutation audit remains
  Session-owned and is removed only by the final AgentSession cascade after required
  cleanup is verified.
- **Verify/finalize** rejects AgentSession tree finalization while actionable bindings
  or binding-specific Work Toolkit State remain. Generic Session ownership remains
  the final database cascade boundary for any other Toolkit State.

Connection, route, resource, conversation-position, principal, interaction,
Agent-scoped grant, and block roots are not cascade-deleted through AgentSession.
Workspace/User deletion cascades account links and transient proof rows within their
own ownership boundary without modifying principals, grants, blocks, messages, or
provider conversation history. Unlink only timestamps the link and never deletes
historical model mutation snapshots.

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

## Routine and Primary Lifecycle

Session Primary Binding authority is cleared by exact disconnect/termination and
physical deletion while unrelated Bindings remain connected. Existing-data
backfill only accepts an unambiguous connected owner; it cannot select or remove
connections to resolve ambiguity.

[Routine lifecycle](../domain/routine.md) is an owner-scoped participant in
archive/purge. Archive removes definitions/records, source checks and pre-start
work. Already-started Routine-only work may finish under the original owner
fences, without recreating removed state. Unrelated active work blocks archive.
Restore does not recreate Routines. Purge waits for preserved started work, then
rechecks namespace absence before finalization. Judgment history follows normal
event retention; Routine observation alone does not refresh autoarchive activity.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/services/external_channel`](../../../../python/apps/azents/src/azents/services/external_channel)
- [`python/apps/azents/src/azents/services/agent_decommission.py`](../../../../python/apps/azents/src/azents/services/agent_decommission.py)
