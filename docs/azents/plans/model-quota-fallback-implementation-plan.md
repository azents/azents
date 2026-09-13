---
title: "Model Quota Fallback Implementation Plan"
created: 2026-09-12
updated: 2026-09-12
tags: [models, agent, reliability, frontend, implementation]
---

# Model Quota Fallback Implementation Plan

## Authority

- Requirements: [Model Quota Fallback Requirements](../requirements/model-260912-quota-fallback.md) (`model-260912/REQ-1` through `REQ-8`)
- ADR: [Model Quota Fallback Decisions](../adr/model-260912-quota-fallback.md) (`model-260912/ADR-D1` through `ADR-D7`)
- Approved Design: [Model Quota Fallback Design](../design/model-260912-quota-fallback.md) revision 2 (`M1` through `M12`)
- Independent reviewer: `/root/design-code-review`
- Design delta: `None`

## Delivery Shape

Use two stacked implementation PRs. The clean storage/API cutover and durable execution authority are
one backend vertical slice; splitting their internal schema and runtime steps into additional PRs
would create review-only fragments that are not independently deployable.

1. `model quota fallback [1/2]: backend vertical slice`
   - Base: `design/model-quota-fallback-260912`
   - Implements `M1` through `M9`, backend portions of `M10` and `M11`, and retained boundaries in
     `M12`.
   - Delivers canonical candidate configuration and migration, strict public v1 plus generated
     clients, durable operation/cooldown/probe/reservation/title state, foreground/compaction/title
     quota progression, DB-derived availability API, applied-route provenance, diagnostics,
     telemetry, deterministic provider controls, and backend tests.
2. `model quota fallback [2/2]: Web recovery and acceptance`
   - Base: phase 1.
   - Completes `M10` and `M11` with the nested Agent/Workspace editor, Composer/picker/mobile
     availability and Primary recovery controls, Storybook, credential-free E2E, complete removal
     evidence, Living Spec promotion, breaking-change release notes, shared snapshot implementation
     date, and temporary-plan cleanup.

## Dependencies and Integration Boundaries

- Phase 1 owns the only stored/public chain contract and every PostgreSQL routing authority. Provider,
  Redis, broker, filesystem, and Runtime I/O remain outside database transactions.
- Phase 2 consumes DB-derived backend authority and adds presentation plus end-to-end acceptance. Redis
  and WebSocket remain best-effort invalidation, never correctness authority.
- The two PRs are a coordinated release unit. The final stack contains no feature flag, legacy
  decoder, dual response field, parallel v2 mutation API, alternate cooldown authority, or synthetic
  provider probe.

## Ownership and Review

`/root` owns implementation, integration, generated artifacts, validation, and corrections.
`/root/design-code-review` is the exact read-only reviewer for both PRs and reviews against the
confirmed Requirements, accepted ADR, approved Design revision 2, current Specs, phase contract,
removal obligations, and stable diff.

## Validation Matrix

- Phase 1: migration data transform/downgrade fence/schema fingerprint; nested configuration CRUD;
  strict stale-caller rejection; operation-state serialization; candidate-health CAS and database
  time; probe/reservation fencing; quota-versus-rate-limit behavior; candidate non-repetition;
  restart/handover; Stop/manual retry; compaction/title progression; provenance, diagnostics,
  metrics/redaction; OpenAPI and generated clients; affected Python and TypeScript quality checks.
- Phase 2: nested editor and one-time Primary settings copy; Composer/picker/Drawer recovery states;
  reserve/cancel/conflict/deadline flows; deterministic provider journal/barriers; concurrent
  Sessions; Redis-empty recovery; required desktop/mobile E2E; Living Specs, release notes,
  implementation dates, plan cleanup, and required CI.

## Removal and Absence Verification

- Remove singular selectable-option storage and public request/response fields.
- Remove direct Agent/Workspace main/lightweight model-selection compatibility paths.
- Replace outer-only JSONB checks, Session-only retry routing authority, and undifferentiated quota
  retry with nested constraints, AgentRun operations, and quota-before-retry progression.
- Replace same-model-only compaction/title behavior and flat Web editor identity.
- Add availability/reservation and immutable actual-route provenance without response-bubble markers.
- Verify through repository search, strict decoding, generated schemas, migration constraints,
  concurrency/recovery tests, browser E2E, and complete Design Authority audit.

## Rollout and External Actions

Release only through the coordinated maintenance cutover in the approved Design. Before any
new-format write, verified database downgrade plus the old release is possible. The first canonical
Agent/Workspace configuration write sets a durable singleton fence; afterward downgrade fails closed
and recovery is roll-forward. No live deployment, migration application, PR merge, or infrastructure
mutation is part of this request.

## Blockers

None. Live provider credentials are optional diagnostics and are not required evidence.
