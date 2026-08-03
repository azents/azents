---
title: "External Channel Session and Discord Thread Automatic Title Requirements"
created: 2026-08-02
updated: 2026-08-03
tags: [external-channel, session, discord, slack, title]
document_role: primary
document_type: requirements
snapshot_id: title-260802
implemented: 2026-08-03
---

# External Channel Session and Discord Thread Automatic Title Requirements

- Snapshot: `title-260802`
- Document reference: `title-260802/REQ`

## Problem

Sessions created from Slack or Discord conversations do not currently receive the same automatic title behavior as direct Azents conversations. Discord threads created by Azents begin with an Agent-derived name, but that name does not become the concise title later generated for the connected Session. Waiting for model-based title generation before admitting the conversation would delay or block the external-channel experience, while unconditionally renaming a thread later could overwrite an existing or human-edited provider title.

## Primary Actor

A human participant who invokes an Azents Agent from an authorized Discord conversation that needs a new Session and an Azents-created thread.

## Primary Scenario

A human sends the first authorized Discord request for a new isolated conversation. Azents creates and admits the connected Session and Discord thread without waiting for model-based title generation, so the conversation is usable immediately under a safe provisional thread name. The existing automatic Session-title lifecycle then derives a concise title from that authorized request. When the first final automatic Session title becomes available, the same title is applied once to the Azents-created Discord thread if its provisional title has not been replaced by a human.

## Supporting Scenarios

- A human starts a new Session from Slack. The Session receives the same automatic title behavior, while Slack has no independently managed thread title.
- A Discord request arrives inside an already existing thread. The Session may receive an automatic title, but the existing Discord thread title remains unchanged.
- The authorized request has little or no useful body text but includes attachments. Safe attachment metadata such as file names and media types contributes to the title input without reading attachment contents solely for title generation.
- An AgentSession has multiple External Channel Bindings. Only a Discord thread explicitly eligible for its own one-time initial title projection may be updated.
- A human changes an Azents-created Discord thread's provisional title before automatic title projection completes. The human title remains unchanged.

## Goals

- Give Slack- and Discord-created Sessions the same useful automatic title behavior as direct Sessions.
- Give an Azents-created Discord thread the connected Session's first final automatic title without delaying Session or thread creation.
- Preserve provider titles that Azents does not own or that a human has taken over.
- Keep title projection independent from Agent reasoning, responses, and explicit Discord tool use.
- Make title update failure non-blocking for Session admission and execution.

## Non-Goals

- Continuous synchronization between Session titles and Discord thread titles.
- Propagating later manual Session-title edits to Discord.
- Propagating later Discord thread-name edits back to the Session.
- Renaming pre-existing or user-created Discord threads.
- Using surrounding `context_only` provider history, Agent responses, or tool results as title-generation input.
- Giving one Discord thread simultaneous title ownership from multiple Agents or Sessions.
- Adding a titled-thread concept to Slack.

## Requirements

### REQ-1. External authorized request as title input

The first human-authored External Channel message that authorizes execution for a newly created Session must be treated as the Session's initial user request for automatic title generation.

**Acceptance criteria**

- A Slack- or Discord-created Session receives an automatic title when its first accepted invocation is promoted.
- Only the message identified as the authorized invocation contributes conversational text to the title input.
- Messages included only as surrounding provider context do not influence the title.
- Messages authored by Bots, Agent output, and tool results do not influence the title.
- When the authorized request's body is absent or insufficient, already available safe attachment names and media types may supplement the title input; attachment contents are not read solely for title generation.

### REQ-2. Existing automatic Session-title behavior

External Channel Sessions must use the same automatic title lifecycle and precedence rules as direct Sessions.

**Acceptance criteria**

- Automatic title work does not delay Session creation, input admission, or Agent execution.
- The Session exposes the existing immediate automatic fallback title before model-based title generation completes when suitable input is available.
- The first successful final automatic title may replace only the matching initial automatic title.
- A manual Session title remains authoritative and cannot be overwritten by delayed automatic generation.
- Title-generation failure does not fail or cancel the external-channel invocation.

### REQ-3. Immediate provisional Discord thread title

When Azents must create a Discord thread for a new external conversation, the thread must become usable without waiting for the final automatic Session title.

**Acceptance criteria**

- Thread creation does not wait for a title-generation model call.
- The new thread initially has a bounded, provider-valid provisional title derived from the selected Agent.
- Multiple Agent routes available before selection do not produce multiple titles; the selected route determines the provisional Agent identity.

### REQ-4. One-shot initial Discord title projection

When the first final automatic Session title becomes available, Azents must make one
best-effort attempt to apply it to each eligible connected Discord thread that Azents
created for that Session.

**Acceptance criteria**

- A qualifying Discord thread displays the first final automatic Session title when
  the thread is ready and Discord accepts the one attempt.
- If the thread is not ready, the process is interrupted, or the provider read or
  update fails, the provisional title remains and Azents does not retry or backfill
  the update.
- A pre-existing Discord thread is not eligible for this update.
- A later Binding does not become eligible merely because it points to the same Session.
- Multiple connected Bindings do not cause unrelated provider conversations to be renamed.
- Later Session-title processing does not initiate another provider rename.

### REQ-5. Human and existing title preservation

Azents must not overwrite a Discord thread title it does not currently own as the provisional initial title.

**Acceptance criteria**

- A Discord thread that existed before Azents connected the Session retains its title.
- If a human changes the provisional title before the automatic update is applied, Azents leaves the human title unchanged.
- Once the initial automatic update has completed or title ownership has been relinquished, subsequent Session-title changes do not rename the thread.
- Subsequent Discord thread-name changes do not modify the Session title.

### REQ-6. System-owned best-effort provider update

Applying the automatic Session title to Discord must be a system-owned external-channel operation, independent from Agent inference and Agent-selected tools.

**Acceptance criteria**

- The Agent is not instructed or required to rename the thread.
- The rename is attempted after the title-generation task while the initial Agent
  turn proceeds independently.
- Provider permission, lifecycle, or temporary delivery failure does not roll back the Session title or block Session execution.
- A disconnected Binding, archived Session, unavailable Agent, or terminally disconnected connection prevents a new rename from being applied.
- Failure, cancellation, process interruption, or unavailable provider state ends the
  attempt without retry, recovery, or another trigger.

### REQ-7. Provider-compatible title presentation

The projected Discord title must remain recognizably equivalent to the Session title while satisfying Discord thread-title constraints.

**Acceptance criteria**

- A Session title that already satisfies Discord constraints is applied without semantic rewriting.
- A title that exceeds Discord's supported length is deterministically shortened while preserving its beginning and remaining non-empty.
- Invalid or empty projected output leaves the provisional Discord title unchanged and does not affect the Session title.

## Fixed Constraints

- One External Channel Resource has at most one connected Binding at a time, while one AgentSession may have multiple independent Bindings.
- Existing manual Session-title precedence remains unchanged.
- Existing user-created Discord thread names remain provider-owned and preserved.
- External provider mutations must respect current connection, route, Binding, Session, and provider-permission lifecycle boundaries.
- Provider title projection is best-effort with respect to Discord availability but must not be coupled to Agent execution success.
- Discord title projection has no retry, reconciliation, backfill, or attempt-history
  guarantee.

## Open Assumptions

- The connected Discord App retains permission to edit a thread that Azents created. If that permission is unavailable, the Session title remains valid and the thread retains its current title.
- Discord does not provide an atomic compare-and-set operation for thread names. The Design must minimize the race between checking the provisional title and applying the automatic title and must not claim a stronger provider guarantee than Discord exposes.

## Confirmation

Confirmed by the requester on 2026-08-02 before ADR and design decisions began.
One-shot failure semantics were clarified by the requester on 2026-08-03 before the
replacement ADR decisions began.
