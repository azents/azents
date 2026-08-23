---
title: "Consistent TurnAction Capability Requirements"
created: 2026-08-23
updated: 2026-08-23
implemented: 2026-08-23
tags: [agent, chat, backend, architecture]
document_role: primary
document_type: requirements
snapshot_id: action-260823
---

# Consistent TurnAction Capability Requirements

- Snapshot: `action-260823`
- Document reference: `action-260823/REQ`

## Problem

TurnAction behavior is currently described independently at composer discovery,
input admission, mailbox preparation, inference preparation, and operation
execution boundaries. A maintainer adding or changing an action can therefore leave
one boundary inconsistent even when the other boundaries compile and pass their
local tests.

## Primary Actor

An Azents maintainer adding or changing a supported TurnAction.

## Primary Scenario

A maintainer adds or changes one TurnAction capability. The action's visibility,
input policy, preparation behavior, and optional operation execution remain
consistent across every supported input boundary, and automated verification fails
when any required capability is missing.

## Supporting Scenarios

- A user sees Goal, cleanup, and projected Skill actions with their current labels,
  message policies, availability hints, and source metadata.
- An internal Agent-managed worktree action remains executable without becoming a
  human-visible composer action.
- A handled Goal or Skill preparation failure remains a recoverable durable
  `system_error` without retrying the consumed mailbox item.

## Goals

- Keep one authoritative action policy for composer and admission behavior.
- Let the domain that owns an action own its state access and semantic behavior.
- Make action preparation and operation execution registration exhaustive.
- Preserve all current user-visible and durable TurnAction behavior.

## Non-Goals

- Supporting third-party or runtime-loaded action plugins.
- Replacing the closed discriminated action payload contract.
- Changing Skill storage, filesystem projection, or managed VFS behavior.
- Changing mailbox FIFO, idempotency, transaction, event, or recovery semantics.
- Making every action a Toolkit-owned capability.
- Adding compatibility aliases or fallback action types.

## Requirements

### REQ-1. Consistent public input policy

Every public TurnAction must expose and enforce one consistent visibility, message,
attachment, and inference-profile policy.

**Acceptance criteria**

- Composer definitions and REST admission use the same policy authority.
- Goal continues to require a non-empty objective with the current maximum length.
- Skill, worktree creation, and worktree cleanup retain their current optional
  message and unsupported-attachment behavior.
- Internal actions cannot appear in the human composer catalog.

### REQ-2. Domain-owned preparation

Goal and Skill preparation must be owned outside generic mailbox orchestration.

**Acceptance criteria**

- Generic mailbox orchestration does not construct Goal or Skill state stores.
- Goal and Skill owners validate state, access their state projections, and produce
  their semantic preparation results.
- Successful and handled-failure durable event behavior remains unchanged.

### REQ-3. Exhaustive operation execution

Every operation TurnAction must have one explicit execution registration.

**Acceptance criteria**

- The generic run executor does not select action-specific operation methods.
- Missing operation execution registration fails deterministic automated
  verification.
- Current context invalidation, run completion, cancellation, owner-generation
  fencing, and terminal handoff behavior remains unchanged.

### REQ-4. Dynamic action discovery

An action owner must be able to contribute zero, one, or many current composer
definitions.

**Acceptance criteria**

- Skill discovery returns projection-dependent definitions with the current
  deduplication, source labels, and relative hints.
- Goal and cleanup definitions remain static except for current state-dependent
  availability hints.
- The generic chat route does not access Skill state or VFS projection details.

### REQ-5. Closed and testable registration

The supported TurnAction set must remain a closed product contract with explicit
application composition.

**Acceptance criteria**

- No import-time or runtime plugin registration is introduced.
- Typed action payloads remain the routing input after ingress.
- Automated coverage verifies policy, preparation, and execution registration for
  every supported action discriminator.

### REQ-6. Behavioral compatibility

The refactor must preserve current public API, durable event, and execution
behavior.

**Acceptance criteria**

- No public request or response schema changes are required.
- Goal, Skill, public worktree, working-folder, and Agent-managed worktree actions
  retain their current observable results.
- Existing deterministic backend and E2E scenarios continue to pass.

## Fixed Constraints

- Registration uses explicit dependency injection and exhaustive typed dispatch.
- Unexpected technical failures raise and retain existing recovery behavior.
- Handled domain failures remain committed values represented as recoverable
  `system_error` events.
- Git-tracked artifacts and user-facing service text remain in English.

## Open Assumptions

- The current public requirement for an inference profile on accepted TurnAction
  writes remains unchanged even when an operation action does not require inference
  preparation.

## Confirmation

Confirmed by the requester on 2026-08-23 through the explicit instruction to solve
GitHub issue #1393 after reviewing and approving its complete scope and acceptance
criteria.
