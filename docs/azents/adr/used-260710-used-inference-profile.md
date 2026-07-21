---
title: "Persist the Session Last-Used Inference Profile"
created: 2026-07-10
tags: [architecture, agent, backend, engine, session, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: used-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0106-session-last-used-inference-profile.md"
---

# used-260710/ADR: Persist the Session Last-Used Inference Profile

## Context

Per-prompt model target and reasoning effort controls should remain sticky within a session. The same default is also needed for runs that are not triggered by a human composer, including continuation and background-driven processing. Passing the profile only in a transient wake-up message would not survive retries, worker handoff, or server restart.

Agent defaults alone are insufficient because they discard the active session's inference choice. Browser-local persistence is also insufficient because backend-triggered runs, other devices, and recovery workers cannot observe it.

Under [time-260710/ADR](./time-260710-time-target-resolution.md), the reusable selection is a model target label plus requested reasoning effort. The resolved model snapshot is run-specific execution provenance and may change when dynamic routing resolves the same target later.

## Decision

Persist the session's last-used requested inference profile on `agent_sessions`.

The session stores nullable fields equivalent to:

- `last_model_target_label`
- `last_reasoning_effort`

After run-time target and effort resolution succeeds for a new `AgentRun`, update these session fields to that run's requested target label and reasoning effort at the atomic activation checkpoint defined by [atomic-260710/ADR](./atomic-260710-atomic-profile-activation.md). The resolved provenance, pending-to-running transition, and session update commit together before provider invocation. A failed resolution or activation does not replace the previous last-used profile.

Profile selection precedence for a new run is:

1. an explicit target and effort supplied by the run-triggering input;
2. the AgentSession's persisted last-used target and effort;
3. the Agent's current default main target and compatible default reasoning effort when the session has never committed a successfully activated run profile.

Every selected or inherited target is resolved against current Agent routing configuration at the new run boundary under [time-260710/ADR](./time-260710-time-target-resolution.md). If an explicit or inherited target cannot resolve, the run fails explicitly. The resolver does not continue down the precedence list as fallback.

Composer UI starts a new session from the Agent default profile and keeps the latest selected profile within that session. Backend-triggered runs follow the same session profile even when no composer request is present.

## Rejected options

### Reset the composer after every prompt

This creates repeated work and makes backend-triggered continuation diverge from the model context the user selected for the session.

### Store the selection only in browser state

Browser state is unavailable to workers, other devices, server recovery, and non-user-triggered execution.

### Persist the last profile on Agent

Agent scope would leak one session's task-specific choice into unrelated sessions and users.

### Persist only the last resolved model snapshot

A frozen snapshot would bypass run-time target resolution and block the dynamic-routing evolution chosen in [time-260710/ADR](./time-260710-time-target-resolution.md).

## Consequences

- `agent_sessions` requires nullable target-label and reasoning-effort columns and repository/service projections.
- New sessions use current Agent defaults until their first resolved run profile commits at the activation checkpoint.
- Continuation and background-triggered runs inherit the last profile without requiring model fields in their wake-up envelope.
- Session reload and multi-device composer state can use server-owned profile state; pending explicit input may still be shown as the immediate unsent/queued UI selection.
- Agent target changes can make a persisted session target invalid; the next inherited run then fails explicitly rather than falling back.
- AgentRun continues to store requested target plus resolved model provenance independently of the session's reusable target state.

## Migration provenance

- Historical source filename: `0106-session-last-used-inference-profile.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
