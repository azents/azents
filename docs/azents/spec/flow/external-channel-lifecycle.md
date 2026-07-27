---
title: "External Channel Lifecycle"
created: 2026-07-22
tags: [backend, external-channel, lifecycle, session, agent, discord]
spec_type: flow
owner: "@Hardtack"
touches_domains: [external-channel, agent, conversation]
code_paths:
  - python/apps/azents/src/azents/core/session_lifecycle.py
  - python/apps/azents/src/azents/repos/external_channel/lifecycle.py
  - python/apps/azents/src/azents/services/external_channel/lifecycle.py
  - python/apps/azents/src/azents/services/external_channel/file_transfer.py
  - python/apps/azents/src/azents/services/external_channel/management.py
  - python/apps/azents/src/azents/services/external_channel/discord_activation.py
  - python/apps/azents/src/azents/services/external_channel/discord_gateway_manager.py
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
last_verified_at: 2026-07-27
spec_version: 16
---

# External Channel Lifecycle

## Direct Management Transitions

Disconnecting a binding terminally marks it disconnected, ends active Channel Work, removes never-projected pending context for that binding route/resource, and commits Activity Tracker cleanup delivery when needed. Canonical provider messages and already projected AgentSession history remain.

Disconnecting a connection accepts every lifecycle and credential state. It
terminalizes the connection, terminates owned active resources/bindings/work, clears
credentials, and commits terminal local state before provider cleanup runs. Repeating
the command is safe. Disconnected connection rows remain durable history roots but
are excluded from the active Single management list. Disconnected Multi Apps remain
readable through Workspace history but reject mutation.

Removing the sole Single App association disconnects the entire App. Removing one
Multi App route generation-fences the connection, marks only that catalog route
removed, disconnects bindings owned by that route, and invalidates its active channel
defaults. It preserves the connection and every other route. A removed Multi route
can be explicitly re-enabled only while the connection is mutable and Multi growth is
rollout-enabled; detached historical Agent snapshots never become routable.

Replacing or clearing a Multi channel default is generation-fenced and never rewrites
an established resource binding. Stale impact previews fail with conflict instead of
applying a destructive mutation against newer state.

Editing a visible Slack connection replaces App ID, HTTP/Socket transport, and the
complete submitted credential set in one operation. It clears stale provider
identity, capability, health, lease, and gap projections and immediately validates
the replacement configuration. No lifecycle status prevents editing a visible
connection, and no transport fallback occurs.

Editing a visible Discord connection replaces the submitted Application identity,
target Guild configuration, and complete Bot credential set in one fenced operation.
It invalidates stale callback selector, Application claim, Gateway lease/checkpoint,
gap, identity, capability, and health projections before callback activation repeats.
Callback activation first persists the new selector hash and Discord Application public
key under the unchanged credential and configuration-generation fences, commits that
provisional PING-only authority, then asks Discord to register the endpoint. A failed
registration clears that provisional authority and moves the connection to
`reconnect_required`; normal interactions are rejected until the final activation
commit. The Gateway Worker can claim only the newly activated configuration; a stale
worker cannot continue mutation after replacement or disconnect.

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

An Allow decision locks the connection, route, resource, binding, admission, and
request before creating or reusing its grant and binding. Slack keeps the existing
`waiting_hydration` activation transition. Discord has no remote-history hydration
adapter, so Allow creates an immediately active binding, ensures active Channel Work,
releases the retained request source through one invocation batch and mailbox item,
then wakes the Session after commit. Repeated Allow decisions reuse the same durable
binding, batch, and mailbox identity. Final Allow, Deny, and Block decisions create a
provider-aware idempotent delete intent when their approval control was delivered.

Every new file download and file-bearing publication revalidates the current Agent,
Session, route, binding, connection, and directional capability. Binding disconnect,
connection disconnect, Session archive, and Agent decommission therefore prevent new
transfers immediately through the existing lifecycle fences. A provider access change or
file deletion is observed at download time. An in-progress outbound provider attempt
retains its existing one-attempt outcome and is never replayed after a lifecycle change.

Provider credential and permission failures move only connection health to
`reconnect_required`; they preserve route relationships, bindings, and work. Slack
App uninstall clears provider credentials and terminalizes provider resources while
preserving the route relationship for later reconfiguration. In-flight validation
results are generation-fenced so they cannot overwrite a newer edit or disconnect.

Discord Gateway credential and non-reconnectable intent or close-code failures
atomically record the fenced gap, release the current Gateway lease, and move only
connection health to `reconnect_required`; they preserve route relationships,
bindings, and work. Recoverable transport failures retain their gap-and-retry path.
Discord callback and Gateway authority are released during disconnect after terminal
local state commits; provider cleanup failure remains a visible post-commit outcome.

## Session Archive and Restore

External Channel is registered as the `session.external-channel` lifecycle participant.

Archive uses the explicit terminal transition policy inside the caller-owned archive transaction:

1. lock active bindings in the Session subtree;
2. mark bindings disconnected and preserve their history;
3. end Channel Work;
4. remove never-projected pending context; and
5. create one cleanup delivery intent for each retained Activity Tracker.

Provider cleanup runs after commit. Failure or an unknown result does not roll back Session archive.
External Channel file transfer adds no stored byte object or file-specific cleanup
participant; only existing metadata, action, and delivery rows follow lifecycle cleanup.

Restore uses `preserve`. It validates that terminal bindings, ended work, removed pending context, and cleanup bookkeeping remain terminal. Restore never reactivates External Channel state; managers must establish new provider state explicitly.

## Permanent Session Purge

Newly fenced jobs include the participant in their immutable purge snapshot. Jobs
that were already fenced before the participant was registered retain their
earlier snapshot and do not retroactively add or execute it. Restrictive
AgentSession ownership still prevents finalization if Session-owned External
Channel roots exist outside that earlier snapshot.

- **Prepare** resolves incomplete delivery bookkeeping without provider execution.
- **Cleanup** deletes Session-owned invocation batches/items, access decisions tied directly to the Session, Channel Work/tasks/actions/delivery rows, and bindings in restrictive ownership order.
- **Verify/finalize** rejects AgentSession tree finalization while actionable binding/work state remains.

Connection, route, resource, canonical event, principal, message, revision, Agent-scoped grant, and block roots are not cascade-deleted through AgentSession.

## Agent Decommission

Agent deletion is asynchronous and irreversible. Its lifecycle status fences new
routing and invocation, then decommission archives/terminalizes owned Session state
through the normal lifecycle participant and commits provider cleanup intents. A
Single App route removal disconnects that App; a Multi App route removal preserves
the Workspace-owned App and its other Agents. Historical routes retain the immutable
Agent snapshot with no routable Agent ID. The finalizer never bypasses restrictive
ownership boundaries.

## Operational Projection

Agent Settings shows active Single App health, reconnect requirement with a
localized safe Discord cause and recovery action, revocation, transport, complete
connection editing, unconditional disconnect, complete provider user IDs for grants
and blocks, and associated Multi Apps as read-only Workspace-managed context.
Workspace integrations owns Multi App setup, catalog, channel defaults, impact
previews, and terminal disconnect. Destructive connection, route, default, grant,
and block actions use in-product confirmation dialogs.

Session Channels remains readable after archive and displays disconnected bindings,
ended work, ordered task state, the Activity Tracker projection state, truncation,
and delivery outcomes. Binding disconnect also uses an in-product confirmation
dialog. Restore controls do not imply provider reactivation.

## Changelog

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
