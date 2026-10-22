---
title: "Interruptible Shell Waiting Requirements"
created: 2026-10-22
updated: 2026-10-22
tags: [runtime, tools, wait]
document_role: primary
document_type: requirements
snapshot_id: shell-261022
---

# Interruptible Shell Waiting Requirements

- Snapshot: `shell-261022`
- Document reference: `shell-261022/REQ`

## Problem

Long shell-result polls delay the next model boundary and processing of user input.

## Primary Context

### Primary System Outcome

An agent can wait for shell completion while remaining responsive to new input,
without consuming command output or stopping the command.

## Supporting Scenarios or Effects

- Agents can execute commands, continue other work, and collect output later.
- Fire-and-forget commands do not affect shared waiting.

## Goals

Preserve early completion, optional waiting, output ownership, and Session isolation.

## Non-Goals

Automatic completion input, automatic Runs, unsolicited output delivery, deployment,
and changes to process stop/retention policy.

## Requirements

### REQ-1. Short shell-result waits

Both shell execution and stdin/result collection accept result-yield windows of at
most ten seconds. Existing defaults remain where they fit that bound. This bound
is not an end-to-end Runtime provisioning or transport latency guarantee.

**Acceptance criteria**

- Requests above 10000 milliseconds are rejected before execution.
- A process that finishes before the requested window returns early.
- Zero-window output collection remains available.

### REQ-2. Interruptible, untargeted waiting

Shared waiting takes only a timeout. Ordinary shell commands participate by default,
without requiring the caller to specify process identifiers.

**Acceptance criteria**

- Shell-only work can keep waiting eligible without descendants.
- Completion before the timeout releases waiting promptly, without a periodic
  process-polling interval.
- New user input releases waiting without terminating commands or consuming input.
- One completed command is not held behind unrelated running commands.

### REQ-3. Explicit fire-and-forget exclusion

The execution call can explicitly exclude a command from shared waiting.

**Acceptance criteria**

- Excluded commands neither keep waiting eligible nor release waiting on completion.
- Excluded commands remain explicitly readable/interactable.
- Starting any command does not force a wait call.

### REQ-4. Separate observation and collection

Waiting reports new lifecycle observations without reading output. Output collection
remains independent.

**Acceptance criteria**

- Waiting does not drain output or consume an exited process.
- An already reported completion does not repeatedly release subsequent waits.
- Completion before wait registration is not missed.
- Cancellation of observation does not cancel execution.

### REQ-5. Preserve authority and existing behavior

**Acceptance criteria**

- Observations are restricted to the current Session and Runner generation.
- Existing user-stop termination and bounded output policies remain unchanged.
- Runtime unavailability cannot indefinitely block mailbox wake-up.
- Existing descendant/mailbox behavior remains when no shell work participates.

## Fixed Constraints

`wait` keeps its time-only input. Runtime processes remain Runner-owned. No
background completion message pipeline or new automatic Run source is introduced.

## Open Assumptions

None concerning the agreed user-visible scope. Internal observation recovery must
be documented and verified without creating a second output owner.

## Confirmation

The requester confirmed time-only waiting, optional collection, explicit
fire-and-forget exclusion, a ten-second shell-yield maximum, and cancellable
non-consuming Runner long-polling during the design discussion on 2026-10-22,
then explicitly requested implementation of that proposal.
