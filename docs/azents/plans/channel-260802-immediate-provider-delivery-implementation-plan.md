---
title: "Immediate External Channel Provider Delivery Implementation Plan"
created: 2026-08-02
tags: [external-channel, slack, discord, backend, frontend, testenv]
---

# Immediate External Channel Provider Delivery Implementation Plan

## Authoritative Inputs

- Requirements:
  [`channel-260802/REQ`](../requirements/channel-260802-immediate-provider-delivery.md)
- ADR:
  [`channel-260802/ADR`](../adr/channel-260802-immediate-provider-delivery.md)
- Approved Design:
  [`channel-260802/DESIGN`](../design/channel-260802-immediate-provider-delivery.md)
- Approved Design revision: `1`
- Approved mechanism IDs: `M1` through `M12`
- Decision owner: Requester
- Independent reviewer: GitHub reviewer `hardtack`
- Design delta: `None`

## Delivery Shape

The destructive cutover must not expose two reachable delivery authorities. Delivery
therefore uses three stacked PRs: one behavior-preserving provider-contract
foundation, one atomic product/schema cutover, and one validation/spec promotion
phase.

| Order | Branch | Base | Deliverable |
| --- | --- | --- | --- |
| 1 | `feat/immediate-provider-delivery-foundation` | `main` | Process-local provider target, operation key, direct plan/outcome contracts, and provider-adapter decoupling without changing current outbox authority |
| 2 | `feat/immediate-provider-delivery-cutover` | Phase 1 | Atomic removal of Action/Delivery persistence, direct Tool/control execution, owner-local projection state, migration, management/OpenAPI/generated-client/Web cutover |
| 3 | `feat/immediate-provider-delivery-validation` | Phase 2 | Deterministic E2E matrix, integrated validation, Living Spec promotion, implementation dates, and plan cleanup |

Create every planned PR before stack-wide CI monitoring. Merge requires separate
explicit requester approval.

## Ownership and Review

The primary agent owns implementation, integration, validation, documentation, and
stack operations. No overlapping implementation owner is assigned.

`hardtack` is the exact independent reviewer for every phase. Review is grounded in
the confirmed Requirements, accepted ADR, approved Design revision 1, current Specs,
the phase execution plan, and the phase diff. Required re-review is limited to
Requirements/Design, security/data-loss, or material convention/interface
corrections.

## Phase 1 — Provider Contract Foundation

### Scope

- Introduce process-local provider target, direct effect plan, operation key, and
  sanitized effect outcome contracts.
- Decouple provider presentation and Discord nonce generation from durable Delivery
  Attempt identity.
- Adapt the current durable workflow to the new provider-facing contract without
  changing persistence, Tool results, recovery, or management behavior.
- Add focused provider-contract and adapter tests.

### Approved mechanisms

- `M2`: the future identifier-free per-effect outcome contract.
- `M6`: live provider target and authority boundary.
- Local prerequisites for `M1`, `M5`, `M7`, and `M10`.

### Removal obligations

None. The current Action/Delivery authority remains unchanged and singular during
this preparatory phase. No direct execution path is reachable yet.

### Validation

- focused Ruff and format checks;
- backend Pyright;
- focused Channel Action, Discord delivery, Slack delivery/presentation tests;
- full backend test suite before PR creation;
- `git diff --check`.

## Phase 2 — Atomic Direct-Execution Cutover

### Scope

- Replace durable Tool Action/Delivery orchestration with commit-then-direct
  process-local execution and ordered immediate outcomes.
- Remove Action duplicate lookup and Engine cancellation recovery.
- Replace every non-Tool durable control with immediate post-commit or post-response
  direct execution.
- Replace lifecycle cleanup intent IDs with in-memory cleanup plans.
- Move Slack current progress identity into Work projection parts, remove Delivery
  FKs and durable pending projection state, and add Access Request current control
  identity.
- Generate one Alembic revision after `772e7ab22a8e`; remove both legacy tables and
  delivery-only PostgreSQL enums without historical backfill.
- Remove the provider-control Worker and Runtime settlement drain.
- Remove management delivery history, regenerate public OpenAPI clients, and remove
  the Web Delivery section.
- Replace focused backend, migration, generated-client, and Web tests.

### Approved mechanisms

`M1` through `M12`.

### Interfaces

- `channel_action` input remains unchanged.
- Tool result becomes binding/state/revision plus ordered `outcomes`.
- `ManagedBinding.deliveries` and `ManagedDelivery` disappear.
- Current Work `projection_state` remains and derives only from owner-local parts.
- No pending provider work, replay API, feature flag, fallback, or mixed-version
  contract is introduced.

### Removal obligations

All Design removal obligations except Living Spec promotion and temporary plan
cleanup.

### Validation

- generated migration upgrade/downgrade and migration tests;
- standard backend Ruff, format, Pyright, and pytest;
- OpenAPI dump and generated Python/TypeScript public clients;
- TypeScript format, lint, typecheck, and build;
- focused Web component/story tests;
- repository-wide absence searches;
- `git diff --check`.

## Phase 3 — Validation, Spec Promotion, and Cleanup

### Scope

- Extend deterministic Slack and Discord E2E for direct outcomes, failure,
  ambiguity, control independence, access cleanup, lifecycle cleanup, management
  contract removal, and Discord Runtime multipart publication.
- Run the complete approved validation matrix and fix implementation defects without
  adding Design authority.
- Run spec review and update current External Channel Specs.
- Set one verified implementation date on Requirements and Design.
- Remove this implementation plan and every phase plan after validation and spec
  promotion are complete.

### Approved mechanisms

Verification of `M1` through `M12`; no new mechanism.

### Validation

- deterministic provider fake contract tests;
- focused and full External Channel E2E;
- backend and E2E Ruff, format, Pyright, pytest;
- TypeScript format, lint, typecheck, and build;
- OpenAPI/generated-client consistency;
- migration and removal absence evidence;
- spec review;
- `git diff --check`.

## Integration Boundaries

- Phase 1 exposes no new runtime mode or second authority.
- Phase 2 is the only authority cutover. Schema, backend, API, generated clients, and
  Web move together.
- Phase 3 may fix defects but cannot add product scope, state, retry behavior,
  compatibility, or another source of truth.
- Historical migrations remain immutable.
- Generated clients are regenerated from OpenAPI and never edited manually.
- E2E state is created through public APIs, UI-equivalent calls, signed callbacks,
  and provider fakes only.

## Removal and Absence Verification

Phase 2 must prove absence of:

- `RDBExternalChannelAction` and `RDBExternalChannelDeliveryAttempt`;
- `external_channel_actions` and `external_channel_delivery_attempts`;
- Delivery Attempt foreign keys, indexes, and PostgreSQL enum types;
- Action lookup/recovery and delivery claim/start/settle/recovery services;
- provider-control Worker composition and idle settlement drains;
- delivery intent IDs in lifecycle/finalizer results;
- `ManagedDelivery`, `ManagedBinding.deliveries`, generated client exports, and Web
  Delivery UI;
- any pending provider-operation query, replay path, compatibility view, or fallback
  authority.

Phase 3 confirms the same absence after integrated validation and promotes current
Specs.

## Rollout and Rollback

- Rollout is one coordinated Phase 2 application/schema cutover.
- Mixed old/new application serving is unsupported.
- The migration downgrade recreates schema without reconstructing deleted history.
- Database backup is the only historical-row recovery boundary.
- No deployment, merge, or live-provider mutation is performed without explicit
  requester approval.

## Blockers

None at plan creation. New material scope or mechanism returns to feature design.
Local implementation discoveries remain within the approved interfaces.

## Plan Cleanup

Delete this plan and all matching phase plans only in Phase 3 after implementation,
validation, spec promotion, implementation-date recording, review, and CI are
complete.
