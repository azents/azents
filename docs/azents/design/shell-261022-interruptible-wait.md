---
title: "Interruptible Shell Waiting Design"
created: 2026-10-22
updated: 2026-10-22
tags: [runtime, tools, wait]
document_role: primary
document_type: design
snapshot_id: shell-261022
---

# Interruptible Shell Waiting Design

## Current Behavior and Gaps

Shell calls await process exit/yield without observing mailbox activity. Empty
stdin polls allow 300 seconds. Shared wait only considers descendants and mailbox.
Output snapshots drain buffers and consume exited processes.

## Architecture and Ownership

Runner retains process ownership. Add `process.observe` with owner Session,
`after_revision`, and timeout, carried by typed protobuf operation payload/result.
Execution records `fire_and_forget`. A Runner-local lifecycle revision and event
are advanced by process completion and terminal cleanup, never by stdout chunks.
Observation checks existing state before waiting, does not acquire interaction locks,
and never drains output. Completed/terminated notices have bounded retention tied
to existing process/tombstone retention. Consumed processes need no extra notice.

Worker starts this operation through the projected Runtime toolkit, never provisioning
a Runtime merely to wait. It races observation against the existing mailbox and
one-second descendant reconciliation. Mailbox is checked first on each wake. A
normal observation timeout is distinct from Runtime failure. Inactive Runtime
projection means no participating shell work; actual operation failures remain
visible rather than becoming false empty results.

## Observation Delivery and Recovery

A completed wait's generic metadata stores Runtime ID, Runner generation, and
observation revision. Repository reads the latest committed position for that
identity, including compacted but retained events. Runner notices are not acknowledged
when responding. Cancellation, lost responses, and failed tool-result admission
therefore cannot silently advance the durable observation position. A restart
creates a new generation and starts observation at zero, preserving existing
missing-process semantics. Existing transcript retention also bounds recovery;
removed transcripts are not a new durable process ledger.

## Interfaces and Behavior

`exec_command.fire_and_forget` defaults false. Execution yields at most 10000 ms;
stdin yields at most 10000 ms and keeps zero-yield collection. `wait` keeps exactly
one timeout field. Its process activity result contains process identifiers and
lifecycle states but no stdout/stderr. New process activity releases wait even when
other processes remain running. Excluded-only Sessions retain existing no-work
behavior. Existing descendant/mailbox-only paths remain available without Runtime.

## Security, Failure, and Cancellation

Runner validates owner Session and current generation. Observation cannot disclose
other Sessions' processes. Observation cancellation only cancels the observation
operation; managed process wait tasks are never cancelled. Existing user-stop
termination is unchanged. Pending local tasks have bounded cleanup so mailbox
handling does not await a slow remote cancellation. Remote operations have explicit
deadlines. Runtime errors are surfaced as tool observations/errors, not success.
No automatic Run, background completion input, or second output buffer is added.

## Migration and Operations

No schema migration or user setting is required. Backend, control library, protobuf,
and Runner ship together. Old Runner capability mismatch is not hidden with polling
or output-drain fallback. Rollback requires reverting the coordinated image/code
change; live processes retain existing generation/Runtime lifecycle boundaries.

## Test Strategy

End-to-end acceptance scenario: start a long command, call time-only wait, insert
user input before completion, verify prompt wait release and subsequent output
collection without process restart. Exercise through existing Runtime/worker test
substrate where available; record unavailable external prerequisites honestly.
Deterministic focused tests cover Runner non-consuming completion, pre-registration
completion, fire-and-forget exclusion, owner isolation, cursor replay, cancellation,
multiple processes, schema caps, mailbox priority, and transport round trips.
Use explicit events/tasks for ordering, not arbitrary sleeps. Run Ruff, type checking,
and affected backend/control/Runner pytest suites, then general PR CI.

## Design Authority

- Design revision: `1`

| ID | Material mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Cancellable owner-scoped long-poll over existing Runner transport | shell-261022/ADR-D1; REQ-2; REQ-5 | decided |
| M2 | Default participation, explicit fire-and-forget | shell-261022/ADR-D2; REQ-3 | decided |
| M3 | Ten-second shell yield cap; independent output collection | shell-261022/REQ-1; REQ-4 | required |
| M4 | Non-consuming lifecycle state with durable result observation position | shell-261022/REQ-4; ADR-D1; existing transcript result authority | derived |
| M5 | Existing process output, stop, generation and retention authority | flow/agent-runtime-control; shell-261022/REQ-5 | existing |

## Removal and Replacement

| Existing behavior | Removal authority | Replacement | Boundary | Verification |
| --- | --- | --- | --- | --- |
| Shell result yields above ten seconds | REQ-1 | Interruptible shared wait | Model schema and Runner validation | Boundary tests and stale prompt search |
| Descendant-only wait eligibility | REQ-2 | Descendant or ordinary-shell eligibility | Wait toolkit | Shell-only and no-work tests |

## Feasibility

The Runner already owns process exit tasks and a bidirectional operation transport.
Generic result metadata and Session transcript storage already exist. No automatic
completion-input mechanism or database migration is needed. Exact focused and CI
verification results are recorded in the PR; feasibility is conditional on those
checks until implementation is verified.

## Design Approval

- Mode: Collaborative
- Decision owner: Requester
- Approved on: 2026-10-22
- Approved scope: The requester explicitly requested implementation of the previously
  presented long-poll proposal with time-only wait, ten-second shell yields,
  explicit fire-and-forget exclusion, and separate result collection.
- Approval boundary: This document records that approved scope and derived existing
  authority boundaries; it does not claim a separate revision-ID approval exchange.
