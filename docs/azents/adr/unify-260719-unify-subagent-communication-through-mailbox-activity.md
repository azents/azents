---
title: "Unify Subagent Communication Through Mailbox Activity"
created: 2026-07-19
tags: [architecture, agent, backend, engine, subagent, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: unify-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0168-unify-subagent-communication-through-mailbox-activity.md"
---

# unify-260719/ADR: Unify Subagent Communication Through Mailbox Activity

## Context

Subagent collaboration currently uses two observation paths. Ordinary `send_message` communication is stored as target-session `agent_message` mailbox input, while `wait_agent` reads terminal child results directly from `AgentRun` projections and advances a separate observation cursor. As a result, an agent blocked in `wait_agent` does not react to ordinary mailbox communication, and terminal-result coordination requires separate delivery, cursor, and polling behavior.

The session wake contract is already source-specific and must remain stable: `send_message` queues mailbox input without starting a target turn, while `spawn_agent` and `followup_task` mark the target session running and send the normal payload-free broker wake-up.

## Decision

Use the current agent's mailbox as the single model-facing inter-agent communication path for both ordinary messages and terminal child results.

- `send_message` continues to enqueue queue-only `agent_message` input without changing target session run state or sending a broker wake-up.
- `spawn_agent` and `followup_task` retain their existing target session wake behavior.
- When a child Run reaches any terminal status—`completed`, `failed`, `stopped`, `interrupted`, or `cancelled`—the child attempts to enqueue a terminal result message in its direct parent's mailbox.
- Terminal result delivery does not start an idle parent turn. An actively executing `wait_agent` observes the mailbox update and ends its wait.
- `wait_agent` no longer accepts an agent target. It observes the current agent's complete mailbox, so any inter-agent mailbox message ends the wait regardless of sender.
- If no mailbox message is available, `wait_agent` also ends when all descendant agents are idle. This is the fallback for terminal failures that prevent a result message from being delivered.
- If some descendants remain active and no mailbox update occurs, `wait_agent` continues until activity or timeout.

`AgentRun` terminal result fields may remain as execution-history and UI projections, but they are no longer the model-facing communication channel used by `wait_agent`.

## Superseded Decisions

This ADR supersedes the following parts of [codex-260706/ADR](./codex-260706-codex-subagent-redesign.md):

- defining `wait_agent` around unread terminal child Run projections;
- returning terminal result content directly from `wait_agent`;
- using the parent observation cursor as the coordination acknowledgment boundary;
- allowing `wait_agent` to select a named target.

[codex-260706/ADR](./codex-260706-codex-subagent-redesign.md) remains authoritative for the SessionAgent tree, input-buffer-backed abstract Mailbox, context forking, collaboration tool set, and the existing source-owned wake policy except where explicitly superseded here.

## Consequences

- Ordinary messages and terminal results use one mailbox delivery and model-lowering path.
- An agent waiting for collaborators can react to intermediate messages without waiting for a child Run to terminate.
- Terminal delivery remains queue-only and does not create unsolicited parent turns.
- The wait fallback depends on reliable descendant activity and idle projection even when no terminal message was delivered.
- Delivery idempotency, terminal result envelope fields, mailbox acknowledgment projection, and exact idle-detection implementation remain implementation-design details to validate before shipping.

## Migration provenance

- Historical source filename: `0168-unify-subagent-communication-through-mailbox-activity.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
