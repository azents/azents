---
title: "Consistent TurnAction Capabilities Design"
created: 2026-08-23
updated: 2026-08-23
implemented: 2026-08-23
tags: [agent, chat, backend, architecture]
document_role: primary
document_type: design
snapshot_id: action-260823
---

# Consistent TurnAction Capabilities Design

- Snapshot: `action-260823`
- Document reference: `action-260823/DESIGN`
- Requirements: [action-260823/REQ](../requirements/action-260823-consistent-turn-actions.md)
- Decisions: [action-260823/ADR](../adr/action-260823-consistent-turn-actions.md)

## Current Behavior and Gaps

Typed action models are authoritative at ingress, and mailbox processing already
uses a closed processor contract. The remaining action-specific authorities are
distributed:

- the chat action endpoint constructs Goal, cleanup, and Skill definitions;
- REST admission repeats message, attachment, and profile rules;
- `MailboxService` selects action processors, classifies inference requirements,
  constructs Goal and Skill stores, and implements both preparations;
- `RunExecutor` repeats operation-action type selection before invoking
  `SessionGitWorktreeService`.

This distribution fails `action-260823/REQ-1` through `REQ-5` even though current
behavior satisfies the compatibility baseline in `REQ-6`.

## Requirement and Decision Traceability

| Requirement | ADR decisions | Design mechanisms |
| --- | --- | --- |
| `action-260823/REQ-1` | `ADR-D1`, `ADR-D2`, `ADR-D3`, `ADR-D5` | Shared typed policy, catalog definitions, generic admission validation |
| `action-260823/REQ-2` | `ADR-D1`, `ADR-D2`, `ADR-D4` | Goal/Skill preparation handlers and semantic result contract |
| `action-260823/REQ-3` | `ADR-D2`, `ADR-D3` | Worker-owned operation executor registry |
| `action-260823/REQ-4` | `ADR-D1`, `ADR-D2`, `ADR-D5` | Skill-owned dynamic catalog provider |
| `action-260823/REQ-5` | `ADR-D1`, `ADR-D2`, `ADR-D4` | Closed typed registry and completeness tests |
| `action-260823/REQ-6` | `ADR-D3`, `ADR-D4`, `ADR-D5` | Behavior-preserving response mapping and unchanged durable outcomes |

## Architecture and Ownership

### Shared capability service

Introduce a service-layer TurnAction capability registry with explicit injected
Goal and Skill dependencies. It owns:

- immutable policy lookup for every persisted action type;
- public-action admission validation;
- composer definition aggregation;
- preparation inference classification;
- typed Goal/Skill preparation dispatch; and
- operation-action classification.

The registry routes only already-decoded typed action models. One exhaustive match
selects the action owner. Each action owner exposes only the facets it supports.

### Shared policy

Each action policy records:

- owner identity;
- visibility: composer, direct public input, or internal;
- message policy and optional maximum length;
- attachment policy;
- whether public admission requires a requested inference profile;
- whether mailbox preparation resolves inference state;
- whether the action is operation-backed.

Goal and Skill are model-producing. Public worktree actions retain required
admission profiles but are not preparation-inference actions. Working-folder and
Agent-managed worktree actions remain internal and operation-backed.

### Composer catalog

The chat route keeps Session authorization and current live snapshot loading. It
passes an immutable catalog context to the capability service and maps returned
domain definitions to `InputActionDefinitionResponse`.

The Goal owner derives the existing warning from current Goal state. The cleanup
owner returns its existing static definition. The Skill owner calls the existing
filesystem/VFS projection loader and returns one definition per deduplicated Skill
projection item. Commands remain owned by the independent command registry.

### Admission

REST TurnAction admission calls the shared policy validator before enqueueing.
Validation preserves the current messages and status codes:

- missing required profile;
- unsupported attachments;
- missing Goal objective; and
- unsupported or internal action.

The generic route branches only between command and TurnAction categories; it does
not enumerate individual TurnAction models.

### Preparation

The capability service receives a preparation context containing the caller
transaction, Session identity, active Run identity, source mailbox identity, and
user-authored content.

Goal and Skill owners return a `TurnActionPreparationResult` containing:

- ordered semantic event descriptions;
- whether the normal user message must be appended;
- the action turn effect; or
- one user-safe handled-failure message.

`MailboxService` converts that result into its normal promoted mailbox items,
creates the generic user message with the already-prepared inference/files
snapshot, maps handled failure to the existing deterministic `system_error`, and
retains append, association, commit, and deletion ownership.

Operation actions return a neutral operation handoff containing the typed action.

### Operation execution

Introduce a Worker-owned operation executor registry injected into `RunExecutor`.
The run executor retains common owner-generation fencing, shutdown admission,
broadcast callbacks, cancellation, pending projection iteration, and aggregation
of context invalidation/run completion.

The registry decodes persisted operation actions and performs the one exhaustive
typed dispatch to `SessionGitWorktreeService`. It owns active-Run requirements for
Agent-managed bridge actions. `RunExecutor` no longer imports or matches individual
operation action models.

## Data, API, and Event Impact

- No database schema or persisted payload change.
- No public OpenAPI request or response shape change.
- No action discriminator change.
- No durable event schema change.
- Existing action-execution state and mailbox identities remain unchanged.

## Failure, Retry, and Recovery

- Policy/admission rejection remains an immediate public 400 response.
- Goal/Skill handled failures return a deterministic failure result and become the
  existing recoverable `system_error` event in the mailbox transaction.
- VFS storage unavailability and invalid selected Skills retain current handled
  behavior.
- Unexpected repository, state, or executor failures raise and preserve existing
  transaction rollback or operation recovery.
- Owner-generation mismatch, shutdown cancellation, user stop, and terminal
  operation handoff remain owned by the existing run boundary.

## Security and Permissions

The change adds no authorization path. Existing Session access checks occur before
catalog discovery or admission. Internal actions remain absent from composer
definitions and cannot enter the public `ChatAction` payload union. The registry
does not accept raw unvalidated action JSON as a routing authority.

## Migration, Rollout, and Rollback

No data migration is required. Ship the capability service, mailbox integration,
and Worker executor integration in one focused PR because mixed internal versions
are not deployed independently.

Rollback is a code rollback to the prior distributed dispatch. Persisted mailbox,
event, and action-execution rows remain compatible in both directions.

## Observability

Retain existing mailbox and operation logs. The registry owner identity is
available for future structured metrics, but this snapshot does not add a new
logging or metric contract.

## Test Strategy

### Primary verification matrix

| Scenario | Expected evidence |
| --- | --- |
| Goal catalog and admission | Existing definition and warning; empty objective rejected; valid action prepares goal and user events |
| Skill catalog and admission | Projection-dependent definitions preserve source hints; valid action prepares skill and optional user event |
| Cleanup action | Existing public definition and optional message policy; neutral preparation and operation execution |
| Direct worktree action | Accepted through shared policy without appearing in slash catalog |
| Internal working-folder and Agent bridge actions | Not catalog-visible; neutral preparation; correct operation executor selected |
| Handled Goal/Skill failure | Deterministic recoverable `system_error`; mailbox item consumed |
| Incomplete registration | Deterministic unit test failure for the missing facet |

### E2E plan

Existing public chat and worktree E2E scenarios are the primary behavior evidence.
No new browser interaction is introduced. Run the existing Goal, Skill, worktree,
mailbox, and operation-action scenarios in CI; add backend integration tests for
the new registry boundaries where E2E cannot observe internal registration
completeness.

### Fixtures and prerequisites

Reuse deterministic Goal, Skill projection, VFS, mailbox, and typed Runner
worktree fixtures. No live external credential is required.

### Evidence and CI policy

Run backend Ruff, the configured type checker, targeted pytest, the applicable
full backend test suite, documentation validation, and existing required E2E CI.
Deterministic tests may not be skipped. Optional live-provider jobs may skip only
when their credential prerequisite is absent.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| TurnAction definition construction in the chat route | `action-260823/REQ-1`, `REQ-4`; `ADR-D1`, `ADR-D5` | Capability catalog definitions | Goal, cleanup, and Skill branches in `/actions` | Route tests and source search |
| TurnAction admission type/policy matches in the chat route | `action-260823/REQ-1`, `REQ-5`; `ADR-D1`, `ADR-D3` | Shared policy validator | REST TurnAction write helpers | Admission tests and source search |
| Goal/Skill store construction and preparation in `MailboxService` | `action-260823/REQ-2`; `ADR-D2`, `ADR-D4` | Domain-owned preparation handlers | Goal/Skill promotion methods and processors | Mailbox tests and dependency/source search |
| Operation action matches in `RunExecutor` | `action-260823/REQ-3`; `ADR-D2` | Worker operation executor registry | Pending execution and execution-method dispatch matches | Executor tests and source search |
| Existing public schemas and persisted state | `action-260823/REQ-6` | Retained unchanged | None | OpenAPI diff and migration absence |

## Feasibility

- Current typed action unions provide one exhaustive routing input: feasible.
- Goal and Skill stores already support caller-transaction methods: feasible.
- Existing Skill projection helpers can move behind an injected catalog owner
  without schema changes: feasible.
- Operation handlers already share one result type and callback contract: feasible.
- Constructor updates affect bounded backend fixtures and do not require a database
  or frontend migration: feasible.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | One explicit closed TurnAction capability registry | `action-260823/ADR-D1`, `action-260823/REQ-5`, existing polymorphic input processor ADR | `decided` |
| M2 | Separate policy, catalog, preparation, and Worker execution facets | `action-260823/ADR-D2`, `action-260823/REQ-1` through `REQ-4` | `decided` |
| M3 | Separate admission-profile and preparation-inference policy | `action-260823/ADR-D3`, `action-260823/REQ-1`, `REQ-3`, `REQ-6` | `decided` |
| M4 | Typed semantic preparation results with handled failures as values | `action-260823/ADR-D4`, `action-260823/REQ-2`, `REQ-6` | `decided` |
| M5 | Skill-owned dynamic composer discovery | `action-260823/ADR-D5`, `action-260823/REQ-4`, existing Skill projection Specs | `decided` |
| M6 | Preserve public schemas, persistence, and durable behavior | `action-260823/REQ-6`, current conversation and execution-loop Specs | `required` |

## Assumptions and Non-Blocking Risks

- Centralizing action construction will change several test fixture constructors;
  this is bounded mechanical work.
- Python heterogeneous capability typing may require explicit closed union methods
  rather than a generic container. This is a local implementation detail as long
  as M1 and completeness verification remain intact.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `건우`
- Approved on: `2026-08-23`
- Approved Design revision: `1`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`
- Approved scope: Implement GitHub issue #1393 as one behavior-preserving closed
  TurnAction capability boundary covering shared policy, dynamic discovery,
  domain-owned preparation, and Worker operation execution.
