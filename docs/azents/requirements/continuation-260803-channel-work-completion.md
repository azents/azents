---
title: "External Channel Continuation Work Completion Requirements"
created: 2026-08-03
implemented: 2026-08-04
tags: [external-channel, agent, channel-work]
document_role: primary
document_type: requirements
snapshot_id: continuation-260803
---

# External Channel Continuation Work Completion Requirements

- Snapshot: `continuation-260803`
- Document reference: `continuation-260803/REQ`

## Problem

Active Channel Work can schedule `external_channel_continuation` after a run. The
Agent needs a way to end that continuation cycle when no further external publication
is required. This operation must not become a general message-ignore or
selective-response capability.

## Primary Actor

A root Agent processing an `external_channel_continuation`.

## Primary Scenario

The Agent receives an `external_channel_continuation` for active Channel Work whose
tasks are all terminal or absent. It completes that Work without publishing to the
provider, so the Work no longer schedules another continuation.

## Supporting Scenarios

- A continuation covering multiple active bindings may complete one eligible binding
  without granting authority over another Session's binding.
- A Tool-result follow-up from the continuation retains the same completion scope.
- New non-continuation input removes continuation-only completion scope.

## Goals

- End eligible Channel Work from its continuation without external publication.
- Stop later `external_channel_continuation` for the completed Work.
- Preserve unfinished Work and all existing provider state.

## Non-Goals

- Deciding whether an incoming External Channel message deserves a response.
- Ignoring an initial External Channel invocation or ordinary user input.
- Adding a general turn-source taxonomy, input-admission policy, or response mode.
- Changing existing `finish`, `continue`, routing, or provider-delivery behavior.

## Requirements

### REQ-1. Continuation-only availability

Silent completion must be available only while processing
`external_channel_continuation`.

**Acceptance criteria**

- Initial External Channel invocations expose only `finish` and `continue`.
- Ordinary, Goal, agent-message, action, and mixed-input boundaries expose only
  `finish` and `continue`.
- A continuation exposes `ignore` only for binding IDs carried by that continuation.
- Tool-result follow-up retains the continuation binding scope until new actionable
  input replaces it.

### REQ-2. Channel Work completion

`ignore` must finish the selected active Channel Work without external publication.

**Acceptance criteria**

- It accepts a binding and no message, title, task update, or files.
- Work with no tasks or only `completed` and `failed` tasks becomes finished.
- The completed Work is no longer eligible for idle continuation.
- No reply, progress update, file, Activity Tracker deletion, or other provider effect
  is produced.

### REQ-3. Unfinished Work preservation

`ignore` must reject Work containing a `pending` or `in_progress` task.

**Acceptance criteria**

- Rejection occurs before canonical Work mutation or provider planning.
- Existing Work and continuation eligibility remain unchanged.

## Fixed Constraints

- Binding and Session authority checks remain mandatory.
- Eligibility is ephemeral and is not persisted as another authorization source.
- Existing Channel Work Toolkit State remains the sole Work authority.

## Open Assumptions

None.

## Confirmation

Confirmed by the requester on 2026-08-03 by clarifying that `ignore` exists only to
end Channel continuation and has no separate selective-response meaning.
