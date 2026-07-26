---
title: "Fifteen-Minute Wait Timeout Design"
created: 2026-07-26
updated: 2026-07-26
tags: [agent, toolkit, engine, frontend]
document_role: primary
document_type: design
snapshot_id: wait-260726
implemented: 2026-07-26
---

# Fifteen-Minute Wait Timeout Design

- Snapshot: `wait-260726`
- Document reference: `wait-260726/DESIGN`
- Requirements: [Fifteen-Minute Wait Timeout Requirements](../requirements/wait-260726-fifteen-minute-timeout.md) (`wait-260726/REQ`)
- ADR: [Fifteen-Minute Wait Timeout](../adr/wait-260726-fifteen-minute-timeout.md) (`wait-260726/ADR`)

## Overview

The existing independent `WaitToolkit` remains the sole runtime owner of the model-visible `wait`
tool. This snapshot changes only its inclusive `timeout_seconds` maximum from 600 to 900 seconds.

## Traceability

| Requirement | ADR decision | Design mechanism |
| --- | --- | --- |
| `wait-260726/REQ-1` | `wait-260726/ADR-D1` | Pydantic input validation accepts 0 through 900 seconds. |
| `wait-260726/REQ-2` | `wait-260726/ADR-D1` | Web known-tool Zod schema uses the same inclusive range. |

## Design

- Update `_WaitInput.timeout_seconds` to `le=900`.
- Update the shared Web wait input schema to `max(900)`.
- Retain the default of 30 seconds, one-second reconciliation interval, structured outcomes, mailbox
  observation, and all Run/session ownership boundaries.
- Do not add persistence, migration, API route, or compatibility behavior.

## Test Strategy

### Primary verification matrix

| Scenario | Expected result |
| --- | --- |
| Runtime `wait` with 900 seconds | The tool accepts the input and returns the existing immediate outcome when no descendants exist. |
| Web presentation for `wait` with 900 seconds | The specialized wait presentation is selected. |
| Web presentation for `wait` with 901 seconds | The call is rejected as invalid arguments. |

### E2E plan

No E2E fixture is required for this schema-only boundary change. The existing end-to-end wait lifecycle,
mailbox activity, and timeout behavior are unchanged; focused runtime and Web unit tests verify the two
independent validation boundaries.

### Fixtures and evidence

Tests use the existing in-memory mailbox observer and deterministic wait service. Evidence is the
focused pytest result and the Web unit-test result, followed by format, lint, and type checks.

### CI policy

Affected Python and Web checks are required. A failure in either validation boundary blocks the change.
