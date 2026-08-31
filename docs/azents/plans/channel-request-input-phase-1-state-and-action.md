---
title: "External Channel Request Input Phase 1 Plan"
created: 2026-08-31
tags: [external-channel, backend, engine, migration, testing]
---

# External Channel Request Input Phase 1 Plan

## Phase Execution Plan

- Phase: `1/2 — canonical awaiting state and direct action`
- Branch/base: `feature/channel-action-request-input` → `design/channel-action-request-input-recreated`
- PR boundary: model-facing `request_input`, schema version 4, delivery-confirmed awaiting settlement, and migration
- Inputs: confirmed `channel-260831/REQ`, accepted ADR-D1 through ADR-D7, approved Design revision 4
- Deliverables: the new mode can publish an ordinary question, preserve active Work, and establish awaiting state only after confirmed delivery
- Non-goals: ingress resume, idle filtering, presence/typing behavior, Living Spec promotion, and final E2E
- Interfaces: `ExternalChannelActionMode`, `ChannelActionInput`, `ChannelWorkState`, `ChannelActionTransition`, `ChannelActionResult`, `ExternalChannelActionService`, Scheduled Task rejection
- Approved Design mechanisms: `M1, M2, M4, M6, M7, M8, M9, M10, M12`
- Authority references: `channel-260831/REQ-1`, `channel-260831/REQ-2`, `channel-260831/REQ-4`, `channel-260831/ADR-D1`, `channel-260831/ADR-D3`, `channel-260831/ADR-D4`, `channel-260831/ADR-D5`, `channel-260831/ADR-D7`
- Design delta: `None`
- Removal obligations: replace terminal/task-rewrite waiting guidance; add no dynamic prompt, interaction route, or lock
- Absence verification: prompt snapshot tests, route and lock-path search, schema validation, and stale-settlement concurrency tests

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Tool contract | `/root` | `core/enums.py`, `engine/tools/external_channel.py` and tests | Approved M1, M12 | New concise mode and validation | Tool schema/prompt tests |
| Canonical state | `/root` | `repos/external_channel/work_state.py`, `work_data.py`, `work.py` and tests | M2, M4, M10 | Version-4 state, request transition, bounded settlement | Repository and concurrency tests |
| Direct delivery | `/root` | `services/external_channel/channel_action.py` and tests | Canonical transition | Awaiting only after all reply parts deliver | Service outcome tests |
| Scheduled boundary | `/root` | `services/scheduled_task/channel.py` and tests | New enum mode | Explicit rejection | Scheduled-task tests |
| Migration | `/root` | Alembic revision, migration tests, revision pointer | Version-4 state | Validated v3-to-v4 upgrade/downgrade | Migration round-trip tests |

- Integration order: enum/tool contract → state model → repository transition/settlement → service settlement → Scheduled rejection → migration → focused validation
- Independent review: `hardtack`; verify Requirements/ADR/Design traceability, stale-result safety, no new lock, migration correctness, and provider-neutral behavior
- Final validation: affected Ruff/format/type checks; focused tool, repository, service, scheduled-task, and migration pytest suites
- Scope-drift check: every phase diff maps to M1/M2/M4/M6/M7/M8/M9/M10/M12; no ingress, presence, new provider UX, or unapproved fallback
- Context checkpoint: record completed interfaces, migration revision, tests, remaining phase-2 integration, and risks in the PR body
