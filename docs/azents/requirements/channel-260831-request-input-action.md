---
title: "External Channel Input Request Requirements"
created: 2026-08-31
updated: 2026-08-31
implemented: 2026-08-31
tags: [external-channel, agent, continuation, reliability]
document_role: primary
document_type: requirements
snapshot_id: channel-260831
---

# External Channel Input Request Requirements

- Snapshot: `channel-260831`
- Document reference: `channel-260831/REQ`

## Problem

During multi-step External Channel work, an Agent may need a participant's answer,
confirmation, or feedback before useful work can continue. Channel Work currently
must remain unfinished to preserve context, but every unfinished Work is eligible for
an automatic idle continuation. Agents therefore tend to finish Work or rewrite its
task list only to prevent an immediate continuation, and forgetting that workaround
can generate an unnecessary follow-up message before the participant responds.

## Primary Actor

An Agent working with a participant through an existing Slack or Discord binding.

## Primary Scenario

The Agent reaches a material question during active Channel Work, sends the question
as an ordinary channel message, and ends the current Run while preserving the Work's
title, tasks, and history. No External Channel continuation is created while the Work
awaits input. The next eligible human message admitted through the same binding
resumes the Work, and normal continuation behavior is available again after that
response Run.

## Supporting Scenarios

- The Agent decides to resume work without waiting and explicitly continues the same
  binding.
- Several bindings have active Work in one Session, and only one is awaiting input.
- Question delivery fails or has an ambiguous outcome.
- A later result from an older input request races with a newer continue action or
  participant message.

## Goals

- Represent active Channel Work that is waiting for participant input without
  finishing it or rewriting unrelated tasks.
- Prevent the current Run from scheduling an unnecessary External Channel
  continuation after a question is delivered.
- Resume continuation eligibility from ordinary same-binding participant input or an
  explicit same-binding continue action.
- Keep bindings and other continuation sources independent.

## Non-Goals

- Adding Discord buttons, modals, or custom interactions for answering the question.
- Adding Slack Block Actions or interactive webhook response handling.
- Correlating a response to a specific provider-native message or interaction token.
- Pausing Goal, Scheduled Task, TurnAction, or another binding's continuation.
- Changing Scheduled Task lifecycle through this Channel Work action.

## Requirements

### REQ-1. Request participant input without finishing Work

An Agent must be able to ask for participant input while preserving active Channel
Work.

**Acceptance criteria**

- The request is delivered as an ordinary External Channel message through the
  selected active binding.
- The Work remains active with its existing title, tasks, progress projection, and
  cycle identity unless the same action explicitly updates supported progress fields.
- The Agent does not need to clear tasks or use a terminal action to stop the current
  Work's automatic continuation.

### REQ-2. Suppress continuation while input is awaited

A successfully delivered input request must make only the selected binding's Work
ineligible for External Channel idle continuation.

**Acceptance criteria**

- Completion of the requesting Run creates no External Channel continuation solely
  for the awaiting binding.
- Active Work on another binding remains eligible.
- Goal, Scheduled Task, and other independent continuation sources remain eligible.
- The awaiting Work remains available to compaction and management projections.
- Awaiting Work stops Slack processing presence and Discord typing while preserving
  its existing Channel Work Tracker and task presentation.

### REQ-3. Resume on same-binding activity

Awaiting state must end when work resumes through the same binding.

**Acceptance criteria**

- Admission of the next eligible human message through the same binding clears the
  awaiting state before its response Run becomes idle.
- An explicit nonterminal continue action on the same binding clears the awaiting
  state.
- Activity on another binding does not clear the awaiting state.
- Terminal finish or ignore behavior remains terminal and does not resume Work.

### REQ-4. Fail open when the question is not confirmed delivered

A participant must not be left waiting on a question that was not confirmed as
visible to them.

**Acceptance criteria**

- Awaiting state becomes authoritative only after the ordinary question reply is
  confirmed delivered.
- Failed, unknown, or not-attempted delivery leaves the Work eligible for normal
  continuation.
- A late result from an older input request cannot restore awaiting state after a
  newer same-binding continue action or admitted participant message.

## Fixed Constraints

- Participant responses use the existing Slack and Discord message-ingress paths.
- The behavior is scoped by exact External Channel binding.
- Normal provider authorization, binding ownership, message limits, file authority,
  and delivery outcome classification continue to apply.
- No provider-specific interactive response surface or webhook protocol is added.
- The feature adds no database, row, table, advisory, or long-lived transaction lock.
  Concurrent state changes use the existing bounded Toolkit State CAS and canonical
  Work revision only.

## Open Assumptions

- The next eligible human message admitted through the same binding is sufficient to
  represent participant input; exact reply-to-message correlation is not required.

## Confirmation

Confirmed by the requester on 2026-08-31 before ADR and Design decisions were
recorded. The requester additionally confirmed that a same-binding continue action
invalidates any earlier awaiting state, that awaiting Work stops Slack processing
presence and Discord typing, and that implementation must not add a new lock.
