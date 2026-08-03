---
title: "Selective External Channel Response"
created: 2026-08-03
tags: [external-channel, agent, architecture, toolkit-state]
document_role: primary
document_type: adr
snapshot_id: channel-260803
---

# Selective External Channel Response

- Snapshot: `channel-260803`
- Requirements: [`channel-260803/REQ`](../requirements/channel-260803-selective-response.md)

## Context

The confirmed Requirements add silent completion for eligible External Channel work and move Channel Work plus its current provider projection from dedicated tables into the existing session-bound Toolkit State authority.

Toolkit State is durable PostgreSQL-backed state identified by Agent, AgentSession, Toolkit namespace, and state name. Its typed versioned JSON payload and optimistic-lock update contract already survive AgentRun boundaries, Worker restart or ownership handoff, and Session archive and restore. Session purge removes it through the existing AgentSession cascade. Goal, Todo, Tool Search, and Toolkit snapshots already use this authority for session-scoped state.

Current Channel Work uses `external_channel_works` for binding-scoped lifecycle, title, tasks, desired progress, and revisions, and `external_channel_work_projection_parts` for retained provider message identity, projection revision, and current outcome state. Ingress creates active Work before execution, Channel Action commits Work transitions before provider I/O, provider outcomes compare current desired revisions, idle continuation and compaction read active Work, Session Channels reads the latest Work, and lifecycle paths finish or delete Work with the owning binding.

The cutover must preserve those observable behaviors while replacing the dedicated storage authority. The External Channel Toolkit can use a typed Toolkit State handle inside caller-owned transactions, while process-local provider effect plans remain outside the persistent state and execute only after the canonical commit.

Mailbox and Event boundaries already distinguish authorized External Channel invocation, External Channel continuation, and ordinary inputs. That typed provenance can be carried to the Toolkit turn boundary directly. Silent-completion authority does not require transcript reconstruction or another durable authorization state.

## Fixed or Derived Outcomes

The following outcomes are already determined and are not decision points:

- Channel Work lifecycle, title, ordered tasks, desired progress, revisions, and current provider projection use one typed session-bound Toolkit State contract as their only canonical authority (`channel-260803/REQ-5`).
- A destructive cutover migrates each binding's currently observable Work and projection, removes `external_channel_works` and `external_channel_work_projection_parts`, and retains no dual-read, dual-write, fallback, or legacy authority (`channel-260803/REQ-5`).
- Existing active Work remains active after migration. For a binding without active Work, the latest currently managed finished Work remains observable. Older non-current Work history has no replacement authority because current management exposes only the latest Work (`channel-260803/REQ-3`, `channel-260803/REQ-5`).
- Current provider message identity, projection status, ordered part identity, and desired revision migrate with Work so later update, cleanup, and stale-result fencing remain valid (`channel-260803/REQ-5`).
- Toolkit State optimistic locking serializes whole-state replacement. Work-level state and desired-progress revisions remain in the typed payload for model-visible state and provider-effect comparison (`channel-260803/REQ-5`).
- Ingress Work activation, Channel Action transitions, binding termination, and lifecycle cleanup update Toolkit State inside their existing caller-owned database transactions. No database transaction remains open across provider I/O (`channel-260803/REQ-5` and unchanged current delivery behavior).
- Idle continuation, compaction continuity, Session Channels management, archive, restore, decommission, and purge resolve the same Toolkit State authority. Common Session purge continues to remove the state through the existing `toolkit_states.session_id` cascade (`channel-260803/REQ-5`).
- `ignore` is one additional Channel Action mode. It does not add a Work status, task status, response mode, provider operation, table, or persistence mechanism (`channel-260803/REQ-2`, `channel-260803/REQ-4`, `channel-260803/REQ-5`).
- The `ignore` input identifies one binding and accepts no message, title, task update, or files. Cross-field constraints remain runtime validation on one provider-compatible top-level object schema (`channel-260803/REQ-2`, `channel-260803/REQ-3`).
- The canonical Toolkit State transition rejects `ignore` when any current task is `pending` or `in_progress`, before mutation. Eligible `ignore` marks Work finished, advances its existing revisions, clears desired progress, and returns no provider effect plan (`channel-260803/REQ-2`, `channel-260803/REQ-3`).
- Silent completion does not send a reply, publish files or progress, or delete an existing Activity Tracker. A retained current provider projection may consequently derive as stale under the unchanged management rules (`channel-260803/REQ-2`).
- Typed mailbox/run input provenance determines whether the current Toolkit turn may expose `ignore`. Tool-only follow-up preserves the originating External Channel scope; ordinary input does not gain it. Transcript reverse-search and durable authorization flags are not introduced (`channel-260803/REQ-4`).
- Pre-discovery response judgment belongs in the External Channel static prompt. Mode behavior and input constraints belong in the Tool description, schema, and validator. No dynamic prompt is introduced (`channel-260803/REQ-1`).
- Ordinary `finish` and `continue`, provider delivery ordering, response-mode eligibility, ingress, routing, and task semantics remain unchanged (`channel-260803/REQ-3`, `channel-260803/REQ-4`, `channel-260803/REQ-5`).

## Decision Backlog

| Order | Decision point | Dependency | Status |
| --- | --- | --- | --- |
| DP1 | Toolkit State granularity for independent binding work | None | Accepted as ADR-D1 |

This backlog contains every unresolved choice that changes persistence identity, contention, bounded-state behavior, or binding independence. If repository analysis reveals another material choice, the complete backlog must be re-briefed before that choice is made.

## Agent-Owned Implementation Categories

After the material decision is accepted, the Design may choose local reversible details without additional requester decisions:

- state model, helper, enum, field, and error-message names;
- migration revision ID and equivalent SQL decomposition;
- Toolkit State store wrapper and CAS retry helper boundaries;
- typed turn-provenance field and adapter names;
- management projection adapters and live-event fixture composition;
- test file placement and generated-client regeneration mechanics; and
- Living Spec wording and local code organization.

These details may not introduce another Work authority, compatibility fallback, provider effect, routing behavior, response mode, task status, or persistence mechanism.

## Decisions

### `channel-260803/ADR-D1` — Store each binding's Channel Work in an independent Toolkit State row

**Affects:** `channel-260803/REQ-2`, `channel-260803/REQ-3`, `channel-260803/REQ-5`

Each External Channel binding owns one typed Toolkit State payload under the `external_channel` namespace and a state name derived from the binding identity. Because Toolkit State identity includes Agent, AgentSession, namespace, and state name, different binding state names produce independent PostgreSQL rows and independent optimistic-lock versions.

The payload owns the binding's current or latest Channel Work lifecycle, title, ordered tasks, state revision, desired progress revision and payload, and current ordered provider projection parts. A new work cycle replaces the binding's finished current payload with a new active cycle rather than creating retained historical Work rows. Existing management exposes only the latest Work, so older non-current Work history receives no replacement authority.

Ingress, Channel Action, provider-outcome settlement, idle continuation, compaction, management, and lifecycle paths first resolve binding authority through the existing relational binding model and then load or update the corresponding binding-specific Toolkit State. Session purge continues to remove every row through the existing AgentSession cascade.

A single AgentSession-wide binding map was rejected because unrelated bindings would share one CAS version and payload-size boundary, causing avoidable conflicts between currently supported parallel Channel Action calls. Per-work-cycle state rows were rejected because they would preserve an unrequired historical store and introduce discovery and cleanup behavior beyond the latest-work product contract.
