---
title: "Consistent TurnAction Capabilities"
created: 2026-08-23
tags: [agent, chat, backend, architecture]
document_role: primary
document_type: adr
snapshot_id: action-260823
---

# Consistent TurnAction Capabilities

- Snapshot: `action-260823`
- Document reference: `action-260823/ADR`
- Requirements: [action-260823/REQ](../requirements/action-260823-consistent-turn-actions.md)

## Context

The current closed `MailboxProcessor` contract solved the original unbounded
input-buffer branching problem, but TurnAction policy and dispatch remain repeated
across the chat API, mailbox preparation, and run executor. Goal and Skill state
access also remains inside `MailboxService`.

The accepted polymorphic-input decision requires explicit constructor-injected
composition and rejects hidden global plugin registration. The new snapshot must
preserve that direction while making the remaining action capabilities consistent.

## Decisions

### action-260823/ADR-D1. Use one closed capability registry

Compose one constructor-injected TurnAction capability registry from the current
domain-owned capabilities. The registry is the authoritative typed dispatcher for
shared policy, composer definitions, preparation, and operation classification.

Routing remains an exhaustive match over typed action models. Do not use import-time
registration, mutable module-global maps, entry points, or runtime plugin discovery.

Affected requirements: `action-260823/REQ-1`, `REQ-2`, `REQ-4`, `REQ-5`.

### action-260823/ADR-D2. Separate policy, preparation, and operation execution facets

One action capability may expose independent facets:

- a shared policy and optional composer definition provider;
- an optional mailbox preparation handler; and
- an optional operation executor.

The capability registry owns cross-facet completeness checks, while each
domain-owned facet receives only its required dependencies. Runtime-specific
operation execution remains in the Worker composition boundary rather than making
the generic action service depend on Worker infrastructure.

Affected requirements: `action-260823/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`.

### action-260823/ADR-D3. Preserve admission and preparation inference as distinct policy

Record both whether a public write requires an inference profile and whether
mailbox preparation must resolve inference state.

This preserves the current contract in which public TurnAction writes carry a
profile while operation-only actions remain neutral during inference preparation.
Collapsing the two concepts would either change the public write contract or
incorrectly classify operation actions as model-producing.

Affected requirements: `action-260823/REQ-1`, `REQ-3`, `REQ-6`.

### action-260823/ADR-D4. Return typed semantic preparation results

Goal and Skill handlers return typed semantic events, optional user-message
promotion intent, a turn effect, or a handled failure. `MailboxService` retains
transaction orchestration, durable append, run association, and source deletion.

Handled failures remain values that become deterministic recoverable
`system_error` events. Unexpected technical failures continue to raise.

Affected requirements: `action-260823/REQ-2`, `REQ-5`, `REQ-6`.

### action-260823/ADR-D5. Keep dynamic Skill discovery in the Skill-owned capability

The Skill capability reads the current filesystem/VFS action projection and
produces zero or more composer definitions. The chat route passes only the
authorized Session context and maps domain definitions to the existing public
response shape.

Affected requirements: `action-260823/REQ-1`, `REQ-4`, `REQ-6`.

## Rejected Options

### Dynamic global action registration

Rejected because the supported action set is a closed product contract and hidden
registration weakens dependency injection, exhaustiveness, and deterministic tests.

### One universal handler interface for every lifecycle

Rejected because composer discovery, transactional preparation, and Worker
operation execution have different dependencies and failure boundaries. Optional
facets preserve one capability identity without creating a service with every
dependency.

### Keep separate matches and add registry-only tests

Rejected because tests would detect some omissions but policy and routing would
still have multiple authorities that can drift.

### Remove the profile requirement from operation-action writes

Rejected because it would change the current public input contract outside the
confirmed compatibility scope.

## Consequences

- Adding an action still requires extending the closed typed union, but all
  lifecycle facets become explicit under one capability composition.
- The generic API and mailbox layers lose Skill-specific and Goal-specific state
  dependencies.
- Worker operation dispatch becomes replaceable and independently testable.
- Some constructor fixtures require the new explicit capability dependencies.
- No database migration or generated public client change is required.
