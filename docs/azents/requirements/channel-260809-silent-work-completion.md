---
title: "External Channel Silent Work Completion Requirements"
created: 2026-08-09
updated: 2026-08-09
implemented: 2026-08-09
tags: [external-channel, agent, toolkit]
document_role: primary
document_type: requirements
snapshot_id: channel-260809
---

# External Channel Silent Work Completion Requirements

- Snapshot: `channel-260809`
- Document reference: `channel-260809/REQ`

## Problem

External Channel Work cannot be silently completed consistently because the `ignore`
action is exposed and authorized only for continuation input. The restriction prevents
an Agent from choosing no external response for initial, ordinary, or mixed input and
can force unnecessary continuation solely because unfinished tasks remain recorded.

## Primary Actor

An Agent handling an active External Channel binding.

## Primary Scenario

While handling any model input boundary, the Agent determines that an active External
Channel Work item should receive no provider-visible response, invokes
`channel_action` with `mode="ignore"`, and observes that the Work finishes silently and
does not schedule another continuation.

## Supporting Scenarios

- The Agent silently completes Work during initial External Channel input.
- The Agent silently completes Work during an External Channel continuation.
- The Agent silently completes Work during ordinary or mixed input when it deliberately
  targets an active binding.
- Existing pending or in-progress task records do not force another continuation after
  the Agent has selected silent completion.

## Goals

- Make `ignore` a normal Channel Action mode on every model input boundary.
- Finish the selected active Channel Work without provider or file effects.
- Prevent later continuation for the silently finished Work.
- Remove input-provenance and unfinished-task restrictions that exist only to limit
  silent completion.

## Non-Goals

- Changing `finish` or `continue` publication behavior.
- Allowing an action to target an inactive or unauthorized binding.
- Creating Channel Work through `ignore` when no active Work exists.
- Changing provider response-mode admission before input reaches the Agent.

## Requirements

### REQ-1. Unconditional mode availability

`ignore` must be available as a Channel Action mode for ordinary, initial External
Channel, continuation, and mixed model input.

**Acceptance criteria**

- The published `channel_action` schema always includes `finish`, `continue`, and
  `ignore`.
- Input provenance does not change schema availability or service authorization.

### REQ-2. Silent active-Work completion

Selecting `ignore` must finish the targeted active Channel Work without external
publication or another continuation.

**Acceptance criteria**

- `ignore` accepts a binding and no message, title, task update, or files.
- The active Work becomes finished and produces no provider effect plan.
- Idle continuation no longer includes the finished Work.

### REQ-3. Agent-owned completion decision

Recorded task status must not prevent the Agent from silently completing active Work.

**Acceptance criteria**

- Work with pending or in-progress tasks can be finished through `ignore`.
- Existing task records remain historical state of the completed Work and do not cause
  provider effects.

### REQ-4. Preserve normal binding authority

Silent completion must use the same active Session, Agent, binding, route, connection,
and resource validation as other Channel Actions.

**Acceptance criteria**

- An inactive or foreign binding remains rejected.
- `ignore` cannot create new Work when the selected binding has no active Work.

## Fixed Constraints

- Successful `ignore` has no provider reply, progress, file, or cleanup effect.
- Existing `finish` and `continue` contracts remain unchanged.
- Historical implemented Requirements, ADRs, and Designs remain immutable.

## Open Assumptions

- None.

## Confirmation

Confirmed by the requester on 2026-08-09 before the corrective ADR and Design were
created.
