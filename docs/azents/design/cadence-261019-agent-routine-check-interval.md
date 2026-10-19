---
title: "Agent Routine Check Interval Design"
created: 2026-10-19
implemented: 2026-10-19
tags: [agent, routine, scheduler, frontend]
document_role: primary
document_type: design
snapshot_id: cadence-261019
---

# Agent Routine Check Interval

## Current System and Scope

`cadence-261019/REQ` records the explicitly delegated settings-to-PR outcome.
Current source discovery joins Agent and uses `last_tick_at + 30 minutes`.
Fenced admission repeats that interval check. Settled judgment advances the
checkpoint to completion. Minimum action delay and the discovery cap are
independent existing contracts in the Routine domain spec.

## Design Authority

Design revision: `1`.

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Agent-owned bounded integer, default/backfill 30 | REQ-1, REQ-3; ADR-D1 | decided |
| M2 | Existing authorized Agent create/read/PATCH, strict integer validation and generated clients | REQ-1, REQ-3; ADR-D1 | decided |
| M3 | SQL due selection and fenced admission use the current Agent interval | REQ-2; ADR-D1 | decided |
| M4 | Existing Scheduler discovery, minimum action delay, FIFO, Stop, checkpoint and notification behavior | REQ-4; Routine domain spec | existing |
| M5 | One localized whole-minute input in Agent profile settings with existing save states | REQ-1, REQ-3, REQ-5 | required |

References in this table are qualified by `cadence-261019` unless stated otherwise.

## Mechanisms and Boundaries

- Add the integer column and named CHECK through a generated Alembic revision;
  update the revision file. Server default fills existing Agents with 30.
- Add a strict bounded integer to Agent domain/read/create/update types and all
  explicit service/repository/API mappings. Create requests may omit it to select
  30; PATCH omission preserves it and explicit null is invalid.
- Due SQL adds `routine_check_interval_minutes * interval '1 minute'` to the
  persisted checkpoint. Fenced admission reads the current Agent value, not a
  stale discovery snapshot. No snapshot is copied into Session state.
- Preserve the regular 30-minute discovery fallback and task definition, so new
  settings are observed on the next existing scheduled scan, not an immediate
  invalidation signal. Existing pending judgments retain identity.
- Extend the existing form schema, initialization, submit payload and tRPC
  generated-client path. Render a bounded NumberInput in profile settings near
  the existing auto-archive field. Use existing permissions and save/error states.
  Explain range/default, increased checking cost, retained 30-minute action delay
  and possible delay before settings apply. Support English and Korean.

## Removal and Replacement

| Existing surface | Authority | Replacement | Boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Hardcoded tick in due SQL and fenced admission | REQ-2; ADR-D1 | Current Agent value | These two scheduling checks only | Search interval uses; scheduler fallback remains intentional |
| Agent schemas, mappings and generated clients without this setting | REQ-1, REQ-3 | Extended existing contracts | Generated artifacts regenerated, not hand-edited | Typecheck and contract tests |
| Fixed-30 description in Routine spec | REQ-1, REQ-2 | Configured interval with unchanged default | Living Spec only | Spec review |

No Routine state, event, execution ownership or notification data is removed.

## Migration, Failure and Operations

Deploy the additive migration before updated application code. Keep default 30.
No data conversion beyond the default population is required. Old application
code can operate with the additional column; prefer application rollback while
retaining the column to preserve configured values. An explicit migration
downgrade drops only the new column and its CHECK.

Existing API errors propagate normally and form input remains on save failure.
There is no new recovery loop, broker call, cache or Redis dependency.
Concurrent settings edits use existing Agent update semantics. Admission rejects
an interval that became longer after discovery. Lowering it can make work due
at the next scheduled scan; existing action-delay constraints still apply.

## Feasibility

Feasible: Agent already owns administrator settings and is joined by source
discovery. Admission already fences Agent before Session and uses database-only
operations. The form has a bounded integer precedent and shared locale/save
flows. No provider, runtime deployment or credential prerequisite is introduced.
The main risk is confusing checking frequency with action frequency; explicit
copy and unchanged-delay regression coverage address that risk.

## Test Strategy

- Primary public API E2E: create default, save/read custom interval, preserve on
  unrelated PATCH, reject invalid values and retain existing access control.
  Extend the existing required Agent API lane without new credential fixtures.
- Database integration: independent Agents, exact boundaries, changed interval
  between discovery and admission, settled-judgment-relative timing, unchanged
  minimum action delay. Reuse isolated PostgreSQL fixtures and fixed aware clocks.
- Storybook interaction contracts: default/custom bounds, cleared/invalid input,
  save failure and saving state with real providers; mobile overflow and themes.
  UI-only matrices belong here rather than new browser E2E journeys.
- Regenerate OpenAPI/Python/TypeScript clients; run backend Ruff/ty/pytest,
  migration tests, web format/lint/typecheck/unit/component/build and full PR CI.
- Evidence: commands, SHA, test totals and native component captures. CI must pass
  with configured skips only; no optional/live provider test is introduced.

## Design Approval

- Mode: Autonomous.
- Decision owner: dedicated technical interviewee `tick-design-owner`.
- Approved on: 2026-10-19, after authority and repository feasibility review.
- Approved Design revision: `1`.
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`, `M5`.
- Scope: one Agent setting through existing API/UI and source scheduling checks.
