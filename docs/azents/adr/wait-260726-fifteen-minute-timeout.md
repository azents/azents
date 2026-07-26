---
title: "Fifteen-Minute Wait Timeout"
created: 2026-07-26
tags: [agent, toolkit, engine, architecture]
document_role: primary
document_type: adr
snapshot_id: wait-260726
---

# Fifteen-Minute Wait Timeout

- Snapshot: `wait-260726`
- Document reference: `wait-260726/ADR`
- Requirements: [Fifteen-Minute Wait Timeout Requirements](../requirements/wait-260726-fifteen-minute-timeout.md) (`wait-260726/REQ`)

## Context

The implemented `mailbox-260726` snapshot set the independent model-visible `wait` tool's inclusive
maximum timeout to 600 seconds. The requester has confirmed a new product contract: one wait call may
last up to fifteen minutes while preserving the existing default and behavior.

## Decision

### Decision Point 1: Maximum timeout

**Status**: Accepted as `wait-260726/ADR-D1`

Set `wait.timeout_seconds` to an inclusive range of 0 through 900 seconds. Keep the 30-second default.
Apply the same limit in runtime validation and the Web known-tool presentation schema.

Affected requirements: `wait-260726/REQ-1`, `wait-260726/REQ-2`.

## Superseded Decisions

This snapshot supersedes only the 0-through-600-second maximum in
[Unified Agent Input Mailbox](./mailbox-260726-unified-agent-input-mailbox.md) (`mailbox-260726/ADR-D6`).
That ADR remains authoritative for all other `wait` ownership, observation, outcome, scheduling, and
prompt decisions.

## Consequences

- Agents can wait for active descendants for up to fifteen minutes in one call.
- Runtime and chat presentation reject values above 900 seconds consistently.
- No database migration, public API change, persistence change, or scheduling change is required.
