---
title: "Selective External Channel Response Implementation Plan"
created: 2026-08-03
tags: [external-channel, toolkit-state, implementation]
---

# Selective External Channel Response Implementation Plan

- Requirements: [`channel-260803/REQ`](../requirements/channel-260803-selective-response.md)
- ADR: [`channel-260803/ADR`](../adr/channel-260803-selective-response.md)
- Approved Design: [`channel-260803/DESIGN`](../design/channel-260803-selective-response.md), revision `1`
- Approved mechanisms: `M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, M11`
- Design delta: `None`
- Implementation owner: `/root`
- Independent reviewer: `/root/channel-260803-reviewer`

## Stack

The feature is delivered as exactly two sequential pull requests.

| PR | Branch dependency | Scope | Approved mechanisms |
| --- | --- | --- | --- |
| `channel-260803 [1/2]: migrate Channel Work to Toolkit State` | `origin/main` | Typed binding state, all Work/projection readers and writers, migration/downgrade, legacy removal, behavior-preserving Specs and tests | `M1, M2, M3, M4, M5, M6, M10, M11` |
| `channel-260803 [2/2]: add selective ignore completion` | PR 1 branch | Typed turn provenance, conditional Tool contract, `ignore`, prompts, selective-response Specs and tests, plan cleanup | `M7, M8, M9, M10` |

PR 1 must be opened before PR 2 begins. Both PRs are created before CI monitoring. PR 2 must remain based on PR 1 until the stack is merged front to back. No separate design, validation, Spec, documentation, or cleanup PR is created.

## Interfaces and Integration Boundaries

- Toolkit State identity is `agent_id`, `session_id`, namespace `external_channel`, and state name `channel_work:{binding_id}`.
- The typed state preserves `work_cycle_id`, Work lifecycle, ordered tasks, revisions, desired progress, and ordered provider projection parts.
- Provider plans remain process-local and settle through matching binding, cycle, part, and desired revision.
- Session Channels retains its current public `ManagedWork` contract.
- PR 1 retains the existing `finish | continue` Tool contract and provider-visible behavior.
- PR 2 adds `ignore` only under eligible typed External Channel provenance.

## Data and Migration

PR 1 generates one Alembic revision through `alembic revision`, backfills active or otherwise latest Work per binding, verifies counts, drops legacy Work/projection storage, and implements a reconstruction downgrade. `db-schemas/rdb/revision` is updated to the generated revision.

## Runtime and Lifecycle

PR 1 updates ingress, Channel Action, initial progress, provider outcome settlement, management, idle continuation, compaction, binding/resource/route/connection/session lifecycle, purge verification, and Agent decommission finalization. Generic Toolkit State Session cascade remains the final purge boundary.

PR 2 carries typed input provenance through mailbox promotion, Run boundary polling, execution, and `TurnContext`. Tool-result follow-ups retain the current source until new actionable input replaces it.

## Test and E2E Work

- Focused repository, service, engine, lifecycle, management, migration, and schema tests run in each owning PR.
- Existing deterministic Slack and Discord E2E journeys provide PR 1 regression evidence.
- PR 2 extends deterministic proxy fixtures and E2E cases for unrelated input, explicit no-response, direct instruction, uncertainty, unfinished tasks, ordinary chat, mixed input, and Tool follow-up.
- Required deterministic tests fail when prerequisites are missing; optional live-provider smoke tests are not acceptance evidence.

## Removal Obligations

PR 1 removes the two dedicated tables, Work ORM models, table-shaped repository methods and fixtures, every legacy reader/writer, the Work-table lifecycle resource entry, and the route-owned Work finalizer check. Repository search and schema inspection prove absence.

PR 2 replaces mandatory-publication prompt wording and the eligible-turn `finish | continue`-only schema. It removes all feature implementation plan files after validation and Spec promotion.

## Spec Impact

PR 1 updates the External Channel domain, delivery, lifecycle, and Toolkit Specs for Toolkit State ownership while preserving selective-response behavior as not yet implemented. PR 2 updates the same current Specs for typed provenance and `ignore`, then records the shared implementation date on Requirements and Design after validation.

## Rollout and External Actions

The PR 1 migration and application deployment are one destructive cutover with immediate old-process replacement. No feature flag, dual-read, dual-write, fallback, or live infrastructure action is part of either PR. Merging or deploying remains requester/operator owned.

## Checkpoints

At each phase boundary record changed interfaces, commands and evidence, completed removal, authority drift, reviewer findings, remaining risks, branch/base, and next phase dependency. Any material Design delta returns to feature design.

## Blockers

None at plan creation.
