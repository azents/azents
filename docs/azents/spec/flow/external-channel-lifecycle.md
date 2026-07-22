---
title: "External Channel Lifecycle"
created: 2026-07-22
tags: [backend, external-channel, lifecycle, session, agent]
spec_type: flow
owner: "@Hardtack"
touches_domains: [external-channel, agent, conversation]
code_paths:
  - python/apps/azents/src/azents/core/session_lifecycle.py
  - python/apps/azents/src/azents/repos/external_channel/lifecycle.py
  - python/apps/azents/src/azents/services/external_channel/lifecycle.py
  - python/apps/azents/src/azents/services/external_channel/management.py
  - python/apps/azents/src/azents/services/session_lifecycle/orchestrator.py
  - python/apps/azents/src/azents/services/session_lifecycle/registry.py
  - python/apps/azents/src/azents/services/archived_session_purge.py
  - python/apps/azents/src/azents/services/agent_decommission.py
  - python/apps/azents/src/azents/repos/agent_decommission_finalizer/**
  - python/apps/azents/src/azents/repos/session_lifecycle_finalizer/**
  - typescript/apps/azents-web/src/features/external-channel-management/**
  - typescript/apps/azents-web/src/features/session-channels/**
last_verified_at: 2026-07-22
spec_version: 3
---

# External Channel Lifecycle

## Direct Management Transitions

Disconnecting a binding terminally marks it disconnected, ends active Channel Work, removes never-projected pending context for that binding route/resource, and commits progress cleanup delivery when needed. Canonical provider messages and already projected AgentSession history remain.

Disconnecting a connection accepts every lifecycle and credential state. It
terminalizes the connection and its Agent route, terminates owned active
resources/bindings/work, clears credentials, and commits terminal local state before
provider cleanup runs. Repeating the command is safe. Disconnected connection rows
remain durable history roots but are excluded from the active management list.

Editing a visible Slack connection replaces App ID, HTTP/Socket transport, and the
complete submitted credential set in one operation. It clears stale provider
identity, capability, health, lease, and gap projections, reactivates the route, and
immediately validates the replacement configuration. No lifecycle status prevents
editing a visible connection, and no transport fallback occurs.

Provider revocation and invalid credentials move connection state through the same durable terminal or reconnect-required boundaries without exposing credentials.

## Session Archive and Restore

External Channel is registered as the `session.external-channel` lifecycle participant.

Archive uses the explicit terminal transition policy inside the caller-owned archive transaction:

1. lock active bindings in the Session subtree;
2. mark bindings disconnected and preserve their history;
3. end Channel Work;
4. remove never-projected pending context; and
5. create one cleanup delivery intent for each projected progress message.

Provider cleanup runs after commit. Failure or an unknown result does not roll back Session archive.

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

Agent deletion is asynchronous and irreversible. Decommission fences new routing and invocation, archives/terminalizes owned Session state through the normal lifecycle participant, commits provider cleanup intents, and removes direct Agent-owned routes and authorization policy only after required lifecycle work is complete. The finalizer never bypasses restrictive ownership boundaries.

## Operational Projection

Agent Settings shows active connection/route health, reconnect requirement,
revocation, transport, complete connection editing, and unconditional disconnect.
Disconnected connections disappear from this active list. Session Channels remains
readable after archive and displays disconnected bindings, ended work, truncation,
and delivery outcomes. Restore controls do not imply provider reactivation.

## Changelog

- **2026-07-22** (spec_version 3) — Made connection disconnect unconditional and idempotent, committed terminal state before provider cleanup, omitted disconnected rows from active management, and replaced reconnect/transport actions with complete Slack configuration editing.
- **2026-07-22** (spec_version 2) — Preserved already-fenced participant snapshots across registry growth while retaining restrictive finalization safety.
- **2026-07-22** (spec_version 1) — Promoted terminal disconnect, archive/restore policy, restrictive purge ownership, post-commit cleanup, and Agent decommission behavior.
