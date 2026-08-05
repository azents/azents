---
title: "Agent Decommission Test-Double Contracts Design"
created: 2026-08-04
updated: 2026-08-04
implemented: 2026-08-05
tags: [backend, testing, lifecycle, external-channel]
document_role: primary
document_type: design
snapshot_id: decommission-260804
---

# Agent Decommission Test-Double Contracts Design

- Snapshot: `decommission-260804`
- Requirements: [`decommission-260804/REQ`](../requirements/decommission-260804-test-double-contracts.md)
- ADR: [`decommission-260804/ADR`](../adr/decommission-260804-test-double-contracts.md)
- Design reference: `decommission-260804/DESIGN`

## Current Behavior and Requirement Gaps

`AgentDecommissionService` owns a bounded scheduler pass, root Session
retirement, direct Agent-owned External Channel cleanup, Runtime terminal-delete
request and acknowledgement fencing, and finalizer eligibility. Production fields
are annotated as their complete concrete repository or service classes. Focused
tests intentionally provide only the operations exercised by each lifecycle path,
so their concrete-field assignments use assignment ignores and several doubles
accept loose `**kwargs` or return untyped namespace projections.

| Requirement | Current gap |
| --- | --- |
| `decommission-260804/REQ-1` | Partial doubles are not statically checked against the coordinator's consumed interface. |
| `decommission-260804/REQ-2` | The ordering test is protected at runtime but its collaborator shapes do not encode transaction-bound archive capabilities. |
| `decommission-260804/REQ-3` | The direct cleanup test uses opaque result values instead of the concrete cleanup result boundary. |
| `decommission-260804/REQ-4` | Concrete production fields unnecessarily impose full-class test-double conformance. |
| `decommission-260804/REQ-5` | Agent decommission assignment diagnostics remain suppressed rather than eliminated. |

## Architecture

### Consumer-side dependency contracts

The coordinator module defines private Protocols beside
`AgentDecommissionService`. A Protocol is created only for a dependency that the
focused tests replace: session management, decommission status, root Session and
run repositories, retention, lifecycle orchestration, External Channel lifecycle,
broker delivery, Agent lookup, direct ExchangeFile cleanup, Runtime lookup, and
terminal Runtime deletion request.

Each method retains its exact async shape and consumed keyword names. Return
values are either existing concrete lifecycle records or narrow read-only
projections containing only the attributes the coordinator reads. Production
classes remain structurally compatible; FastAPI `Depends` metadata continues to
point at the existing concrete providers.

### Lifecycle and ownership preservation

The coordinator control flow is unchanged:

1. Root-tree retirement records stop intent, dispatches External Channel archive
   participation before root archive, schedules retention and persists status in
   the same transaction, commits, then consumes captured provider cleanup and
   emits broker stop signals.
2. Direct Agent-root cleanup requests terminal deletion only for an immutable
   provider-resource binding; captures External Channel cleanup plans; purges
   captured provider state before expiring unbound files; commits; consumes plans;
   deletes blobs; and blocks finalization until acknowledgement is durable.
3. No contract exposes a Workspace-owned Multi App mutation, so Agent
   decommission cannot gain that authority through this typing boundary.

Focused doubles replace loose keyword sinks and namespace values with explicit
method signatures and typed small records. They continue to assert transaction
and post-commit ordering without simulating unconsumed production behavior.

## Interfaces and Contracts

The contracts are module-private typing interfaces. No public API, generated
client, database schema, event, configuration, scheduler, dependency-provider,
or Runtime Provider protocol changes.

## Security and Permission Boundaries

This change does not grant cleanup authority. The existing repository and
External Channel lifecycle service remain the only code paths that mutate direct
Agent roots. Workspace-owned Multi App routes and connections remain outside every
Agent decommission Protocol.

## Migration, Rollout, and Rollback

No migration, deployment ordering, configuration, or staged rollout is required.
Rollback is a source revert; persisted jobs, retention state, Runtime state, and
External Channel records are unaffected.

## Failure, Retry, and Recovery

The existing `CancelledError` propagation, bounded retry attribution, lease-loss
errors, transaction commits, provider cleanup timing, and Runtime acknowledgement
fence are unchanged. Protocols only make the already-consumed behavior statically
visible.

## Observability and Operational Risk

No telemetry or operational control changes. The main implementation risk is
accidentally widening a Protocol beyond the coordinator's use, which is avoided
by defining only consumed operations and result attributes. A future call-site
addition must update the focused fake and therefore fails static checking until
its test boundary is explicit.

## Requirement and ADR Traceability

| Requirement or ADR | Design mechanisms | Primary verification |
| --- | --- | --- |
| `decommission-260804/REQ-1`, `ADR-D1` | Private consumer-side collaborator Protocols with exact calls and projections | `ty` accepts every focused fake without assignment suppression |
| `decommission-260804/REQ-2`, `ADR-D2` | Typed archive, retention, lifecycle, and broker test collaborators | Focused root-retirement ordering test |
| `decommission-260804/REQ-3`, `ADR-D2` | Typed External Channel cleanup, Runtime, and ExchangeFile collaborators using concrete cleanup records | Focused direct-cleanup and terminal-delete tests |
| `decommission-260804/REQ-4` | Existing concrete `Depends` providers structurally satisfy private Protocols | Backend Pyright and focused tests |
| `decommission-260804/REQ-5` | Remove decommission fake-assignment ignores and record `ty` measurement | Full `ty`, backend test suite, migration analysis note |

## Test Strategy

### E2E primary verification matrix

| Journey | Required evidence |
| --- | --- |
| Root Session retirement | External Channel archive participation occurs before root archive; cleanup and broker stop happen after commit. |
| Direct Agent-root cleanup | Provider-state purge precedes unbound-file expiration; captured cleanup is consumed after commit. |
| Bound Runtime finalization fence | Terminal deletion is requested for an immutable provider-resource binding and acknowledgement remains required. |

### E2E plan

The existing deterministic backend lifecycle tests are the primary feasible
evidence because this change alters only static test collaborator boundaries and
does not expose a new user journey. Existing end-to-end lifecycle coverage remains
the product-level authority; no live provider operation is introduced or required
for this typing-only change.

### Lower-level verification and fixtures

Run the focused `agent_decommission_test.py` tests with typed transaction,
lifecycle, cleanup, Runtime, and broker doubles. Run backend `ty`, Pyright, and
the complete backend pytest suite. No new testenv seed, credential, browser, or
provider fixture is required because no runtime behavior changes.

### Evidence, CI, and skip policy

Run Ruff on changed Python files, backend `ty check --error-on-warning`, backend
Pyright, the focused test file, and the full backend test suite. CI must run the
normal backend checks. A local infrastructure or external-service limitation may
be recorded, but does not waive the deterministic typing and test requirements.

## Alternatives and Non-Blocking Risks

Using concrete production classes plus expanded full-featured fakes would obscure
the consumer boundary and couple these tests to unrelated methods. Runtime adapters
or new providers would duplicate already-valid production composition. Neither is
needed for a static-only correction.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Define private consumer-side Protocols for exactly the Agent decommission collaborators replaced by focused tests, while retaining concrete dependency providers. | `decommission-260804/REQ-1`, `REQ-4`, `decommission-260804/ADR-D1` | `decided` |
| M2 | Preserve typed root-retirement transaction and post-commit ordering, including captured External Channel cleanup plans and broker stop signals. | `decommission-260804/REQ-2`, `decommission-260804/ADR-D2`, existing Agent and External Channel lifecycle specifications | `existing` |
| M3 | Preserve direct Agent-root cleanup ordering, immutable Runtime binding condition, acknowledgement fence, and exclusion of Workspace-owned Multi App authority. | `decommission-260804/REQ-3`, `REQ-4`, `decommission-260804/ADR-D2`, existing External Channel and Runtime Control specifications | `existing` |
| M4 | Remove assignment suppressions by making focused fakes satisfy the exact consumed Protocols and validate with backend typing and tests. | `decommission-260804/REQ-5` | `required` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Concrete collaborator field types as the focused-test substitution boundary | `decommission-260804/ADR-D1` | Private consumer-side Protocol annotations; concrete providers remain | `AgentDecommissionService` injected collaborator annotations only | Focused tests assign typed partial doubles without assignment ignores |
| Loose `**kwargs` and namespace result doubles for consumed lifecycle operations | `decommission-260804/REQ-1`, `ADR-D2` | Explicit method keywords and typed consumed result records/projections | `agent_decommission_test.py` doubles only | Static checking rejects incomplete keyword or result shapes |
| Agent decommission lifecycle logic, persistence, providers, events, scheduler behavior, and Workspace-owned Multi App authority | None; repository-grounded analysis finds no removal obligation | Existing behavior | None | Diff contains no behavior or provider-composition change |

## Design Approval

- Mode: `Autonomous`
- Decision owner: `delegated implementation agent`
- Approved on: 2026-08-04
- Approved Design revision: `1`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`
- Approved scope: Replace only Agent decommission focused-test collaborator
  boundaries with private consumer Protocols, remove incompatible fake assignment
  suppressions, and preserve every existing lifecycle and ownership contract.
