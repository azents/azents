---
title: "Agent Decommission Test-Double Contracts"
created: 2026-08-04
tags: [backend, testing, lifecycle, external-channel]
document_role: primary
document_type: adr
snapshot_id: decommission-260804
---

# Agent Decommission Test-Double Contracts

- Snapshot: `decommission-260804`
- Document reference: `decommission-260804/ADR`
- Requirements: [Agent Decommission Test-Double Contracts Requirements](../requirements/decommission-260804-test-double-contracts.md) (`decommission-260804/REQ`)
- Decision mode: Autonomous
- Decision owner: `delegated implementation agent`

## Context

The Agent decommission coordinator coordinates repository, lifecycle, broker, and
Runtime collaborators across multiple transaction and post-commit boundaries. Its
focused tests inject small collaborators that prove those boundaries, but the
coordinator currently annotates every injected field as a complete concrete
production class. The partial test doubles therefore require suppressed
assignments and cannot statically prove the exact methods, keyword arguments, or
result projections the coordinator consumes.

The existing lifecycle authority is unchanged and remains outside this typing
cleanup. The Agent specification requires decommission to retire Agent-owned
Sessions through archive and retention rather than cascade deletion. The External
Channel lifecycle specification requires transaction-local cleanup plans to be
captured before commit and consumed after commit. The Runtime control specification
requires terminal deletion acknowledgement for the current durable generation
before Agent finalization.

## Decisions

### decommission-260804/ADR-D1: Declare internal consumer-side collaborator Protocols

**Affected requirements:** `decommission-260804/REQ-1`,
`decommission-260804/REQ-4`, `decommission-260804/REQ-5`

`AgentDecommissionService` declares internal Protocols for every collaborator
whose focused tests substitute a partial implementation. Each Protocol contains
only the methods and result attributes the coordinator consumes, preserving exact
async behavior, positional and keyword parameter names, and consumed result
types. The production dependency providers continue to instantiate the current
concrete repositories and services, which satisfy these Protocols structurally.

The Protocols remain private to the coordinator module. They do not create a
runtime adapter, a new DI registration, a public interface, or a generalized
repository abstraction.

**Rejected alternatives:**

- Retaining concrete collaborator annotations and suppressing fake assignments was
  rejected because it leaves consumed capability drift invisible to static
  checking.
- Expanding every fake to implement each full production class was rejected
  because the test boundary would then claim unsupported capabilities and become
  coupled to unrelated behavior.
- Changing providers or registering adapter implementations was rejected because
  the production composition and runtime behavior already meet the required
  boundary.

### decommission-260804/ADR-D2: Keep lifecycle result records and ordering authoritative

**Affected requirements:** `decommission-260804/REQ-2`,
`decommission-260804/REQ-3`, `decommission-260804/REQ-4`

The collaborator contracts use the existing lifecycle result records and preserve
the existing coordinator ordering. External Channel archive participation remains
inside the caller-owned root archive transaction; cleanup plans remain captured
before commit and consumed after commit; direct Agent-owned cleanup still purges
captured provider state before expiring unbound files; and terminal Runtime
deletion remains conditional on immutable provider-resource binding and durable
acknowledgement.

No Protocol may broaden Agent decommission authority to Workspace-owned Multi App
state. No transaction, retry, cancellation, scheduler, persistence, event, or
provider cleanup behavior changes in this snapshot.

**Rejected alternatives:**

- Replacing lifecycle result records with test-only opaque values was rejected
  because cleanup plan and acknowledgement boundaries would no longer be checked
  by the coordinator's typed contract.
- Moving post-commit cleanup into a fake-only code path was rejected because it
  would weaken the production lifecycle ordering under test.

## Consequences

- Focused test doubles can be assigned without assignment ignores while remaining
  constrained to the coordinator's actual consumed capabilities.
- Production DI and runtime execution continue using the same concrete
  collaborators.
- A future coordinator call-site change produces a static incompatibility in its
  focused collaborator rather than relying on a later test failure.
- This snapshot changes neither the current lifecycle specifications nor their
  implementation authority.
