---
title: "External Channel Request Input Implementation Plan"
created: 2026-08-31
tags: [external-channel, backend, engine, testing]
---

# External Channel Request Input Implementation Plan

- Requirements: [channel-260831/REQ](../requirements/channel-260831-request-input-action.md)
- ADR: [channel-260831/ADR](../adr/channel-260831-request-input-action.md)
- Design: [channel-260831/DESIGN](../design/channel-260831-request-input-action.md)
- Approved Design revision: `4`
- Approved mechanisms: `M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, M11, M12`
- Design delta: `None`
- Independent reviewer: `hardtack`

## Delivery Shape

1. `request input [1/2]: add awaiting work state`
   - Add the model-facing mode, canonical schema version 4, direct action settlement, migration, and focused repository/service/tool tests.
2. `request input [2/2]: resume channel work from participant input`
   - Add ingress resume, idle filtering, compaction state, Slack/Discord presence behavior, E2E coverage, Living Spec promotion, implementation dates, and plan cleanup.

The second PR is based on the first. Both implementation PRs are based transitively on the approved Design PR.

## Interfaces and Dependencies

- `ExternalChannelActionMode.REQUEST_INPUT` is the sole new model-facing mode.
- `ChannelWorkState.awaiting_input_run_id` is the sole persisted awaiting marker.
- `ChannelActionTransition` carries the exact Work cycle and state revision captured before provider delivery.
- `ChannelActionResult` exposes whether awaiting state was established and the final canonical state revision.
- Same-binding canonical mailbox creation and explicit `continue` are the only resume transitions.
- Existing Toolkit State CAS and `state_revision` remain the only concurrency fence.
- Scheduled Task-bound Channel Action rejects `request_input`.
- No public API or generated client change is planned.

## Validation Matrix

- Focused tool, repository, service, scheduled-task, ingress, idle-hook, presence, typing, compaction, and migration tests.
- Ruff, formatting, configured type checker, and affected pytest suites for `python/apps/azents`.
- Deterministic External Channel E2E for Slack and Discord lifecycle behavior.
- Documentation snapshot validation and `/spec-review` before implementation completion.
- Required CI on every PR; no live provider credentials required.

## Removal and Absence Verification

- Replace task-clearing or terminal-mode waiting guidance with `request_input` guidance.
- Remove unconditional idle continuation eligibility for awaiting bindings.
- Add no transient suppression, provider interaction callback, new lock, new persistence authority, or dynamic prompt.
- Verify absence through targeted repository search, concurrency tests, route inventory, prompt snapshots, and E2E evidence.

## Rollout

- Generate a validated Channel Work Toolkit State version 3-to-4 migration.
- Require a coordinated homogeneous backend restart before the new mode is used.
- No feature flag or mixed-version compatibility path is added.

## Cleanup

After phase 2 validation and Living Spec promotion, delete this plan and both phase execution plans. Requirements and Design receive the same `implemented` date only after all verification passes.
