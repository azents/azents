---
title: "Agent Decommission Test-Double Contracts Requirements"
created: 2026-08-04
tags: [backend, testing, lifecycle, external-channel]
document_role: primary
document_type: requirements
snapshot_id: decommission-260804
implemented: 2026-08-05
---

# Agent Decommission Test-Double Contracts Requirements

- Snapshot: `decommission-260804`
- Document reference: `decommission-260804/REQ`

## Problem

Agent decommission lifecycle tests currently inject partial doubles into concrete service and repository dependencies. The tests exercise important lifecycle ordering, but the type checker cannot verify that the doubles implement the dependencies consumed by the decommission coordinator.

## Primary Actor

Backend maintainer changing or validating Agent decommission lifecycle behavior.

## Primary Scenario

When a maintainer changes the decommission coordinator or its focused lifecycle tests, the test setup supplies collaborators that express every capability the coordinator consumes. The type checker reports a missing or incompatible capability before the test runs, while the existing test assertions continue to prove the durable lifecycle ordering and ownership boundaries.

## Supporting Scenarios

- A maintainer validates root Session retirement, including External Channel participant termination before root archive and provider cleanup only after commit.
- A maintainer validates direct Agent-owned External Channel cleanup and Runtime terminal-delete acknowledgement without affecting Workspace-owned Multi App authority.
- The production dependency container continues to resolve the existing concrete implementations without a runtime behavior change.

## Goals

- Make the Agent decommission focused test doubles statically compatible with the coordinator dependencies they exercise.
- Preserve the current decommission lifecycle, transaction boundaries, ownership model, and failure behavior.
- Remove checker suppressions that hide incompatible collaborator injection in the affected tests.

## Non-Goals

- Changing Agent deletion, Session archive, retention, Runtime finalization, or External Channel lifecycle behavior.
- Changing public API, event, persistence, migration, scheduler, or dependency-provider behavior.
- Redesigning the general Session lifecycle registry or External Channel ownership model.
- Reworking unrelated backend `ty` diagnostic categories.

## Requirements

### REQ-1. Lifecycle-preserving collaborator validation

The decommission coordinator test boundary must validate the precise collaborator capabilities exercised by each decommission path.

**Acceptance criteria**

- Focused test doubles are accepted without casts, `type: ignore`, or checker-only dynamic assignment.
- Missing, incompatible, or keyword-incompatible consumed capabilities are reported by static checking.
- Capabilities not consumed by the decommission coordinator are not required from focused test doubles.

### REQ-2. Root Session retirement preservation

The typed test boundary must continue to verify the existing root Session retirement lifecycle.

**Acceptance criteria**

- External Channel archive participation occurs before root Session archive in the caller-owned transaction.
- Retention purge scheduling and durable decommission status update occur before the transaction commit.
- Captured provider cleanup runs only after the transaction commits, and stop signals remain post-commit.

### REQ-3. Direct Agent-root cleanup preservation

The typed test boundary must continue to verify the existing cleanup and finalization fences for direct Agent-owned resources.

**Acceptance criteria**

- External Channel cleanup and provider-state purge retain their existing order relative to unbound-file expiration.
- Terminal Runtime deletion remains conditional on the immutable Provider resource binding.
- Finalization remains blocked until terminal Runtime deletion acknowledgement is durable.
- Workspace-owned Multi App authority is not removed or widened by Agent decommission.

### REQ-4. Production integration continuity

The current production implementations and dependency providers must remain usable by the decommission coordinator without runtime adaptation.

**Acceptance criteria**

- Production dependency injection resolves the existing concrete collaborators.
- No public API, schema, migration, configuration, or scheduler contract changes.
- Existing error propagation, retry attribution, transaction ownership, and cancellation behavior remain unchanged.

### REQ-5. Verifiable type-cleanup delivery

The decommission test-double group must be delivered as a verifiable backend typing cleanup.

**Acceptance criteria**

- The identified Agent decommission test-double `ty` diagnostics are eliminated.
- Focused decommission tests, backend Pyright, and the full backend test suite pass.
- The documented backend `ty` measurement records the post-change count and any intentionally excluded work.

## Fixed Constraints

- Existing External Channel lifecycle semantics and participant ordering are authoritative.
- Provider cleanup plans remain process-local, captured before commit and executed only after durable terminal state commits.
- Redis or transient broker state is not an authority for decommission correctness.
- No casts, new type ignores, compatibility fallback, or broad exception handling may be introduced solely to satisfy a type checker.
- The change remains a stacked PR follow-up and must not merge without explicit requester approval.

## Open Assumptions

- The current concrete collaborators structurally satisfy the exact consumer-side contracts needed by the coordinator.
- Existing focused tests provide sufficient lifecycle evidence once their collaborator contracts are typed.

## Confirmation

Confirmed by the requester on 2026-08-04 before ADR and design decisions began.
