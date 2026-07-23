---
title: "Todo-Owned Slack Activity Indicator Design"
created: 2026-07-23
tags: [slack, external-channel, activity, delivery, backend]
document_role: primary
document_type: design
snapshot_id: indicator-260723
---

# Todo-Owned Slack Activity Indicator Design

- Snapshot: `indicator-260723`
- Requirements: [`indicator-260723/REQ`](../requirements/indicator-260723-todo-owned-progress.md)
- ADR: [`indicator-260723/ADR`](../adr/indicator-260723-todo-owned-progress.md)

## Scope and Traceability

| Requirement | Decision | Mechanism |
| --- | --- | --- |
| `REQ-1` | `ADR-D1` | Conditional summary-card `status` based on whether ordered Todos exist |

## Presentation

The renderer always creates the stable `activity-status` task card. It adds
`status: in_progress` only when `tasks` is empty. When one or more task cards follow,
the summary card contains only its ID and title. Todo status mapping remains
unchanged: pending omits status, in-progress uses `in_progress`, and completed uses
`complete`.

Persisted-state recovery calls the same renderer, so restored and live Tracker
payloads cannot diverge.

## API, Persistence, and Migration Impact

The durable desired payload is unchanged. No API, generated client, or database
migration changes are required.

## Test Strategy

### Verification matrix

| Behavior | Primary evidence |
| --- | --- |
| Empty Todo list keeps summary progress | Pure renderer test |
| Non-empty Todo list removes summary status | Exact Block Kit renderer test |
| Active Todo keeps progress status | Exact Block Kit renderer test |
| Persisted recovery follows the same rule | Persisted renderer test |

### CI and acceptance

Ruff, Pyright, focused renderer tests, documentation validation, deterministic E2E,
and required PR CI must pass. The Slack payload remains read-only and requires no
live credential for deterministic verification.
