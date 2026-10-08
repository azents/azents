---
title: "Independent Runtime Reads Design"
created: 2026-10-04
tags: [concurrency, runtime, read-paths]
document_role: primary
document_type: design
snapshot_id: readleaves-261004
---

# Independent Runtime Reads Design

- Revision: 1
- Authority: [Requirements](../requirements/readleaves-261004-independent-runtime-reads.md)
  and [ADR D1](../adr/readleaves-261004-independent-runtime-reads.md).

## M1. Ordinary descriptive SELECT

Remove conditional FOR UPDATE and its optional/required `for_update` argument from
Provider contract/config revision getters and Runtime infrastructure Profile,
Workspace Profile and retained configuration-state getters. Accept `ReadSession`
and use its read_session attribute. Update caller and fake declarations without
removing mutation admission/version/generation checks elsewhere.

No schema, cache, provider mode or API change is required. The current caller's
ReadWrite transaction may still supply the read capability, but independent
consumer examples use ReadOnlySession.

## Design Authority

Revision 1 contains only M1, derived from the requester-confirmed lag-tolerant
read outcome in REQ-1 and the mutation-preservation constraint in REQ-2/ADR D1.
No new product decision, source of truth or optional runtime mode is introduced.

## Removal and Replacement

Remove the five getters' lock flags and conditional SELECT locks; replace them
with ordinary ReadSession reads. Update every caller and fake signature.
The removal boundary is this phase, verified by source inventory/type checks and
actual DB read-only execution. Retain mutation fencing outside these getters.
No schema, configuration, generated-client or persisted-state removal is needed.

## Design Approval

Mode: requester-directed implementation. Decision owner: requester.
Scope confirmed on 2026-10-04: lag-tolerant independent reads and the three
mutation exceptions, followed by implementation after the foundation PR.
Revision 1 authority set: M1 under REQ-1/REQ-2 and ADR D1. This records only that
fixed scope; it does not claim approval for later owner/lifecycle replacements.

## Test Strategy

An actual PostgreSQL test holds a configuration/Profile writer transaction and
an uncommitted Profile rename while a separate ReadOnlySession calls the getters.
Reads must return committed evidence without acquiring a conflicting row lock or
seeing the uncommitted rename. Verify absent references remain None. Use a bounded
statement timeout to fail a blocking implementation, not sleeps to order tasks.

Run related repository, resolution, reconciliation, provider-policy and Runtime
state-sink tests plus whole-backend typing/lint and required CI. Verify all removed
getter lock flags have no callers and no fallback/locked alias remains. Review
configuration evidence writers separately to ensure critical mutation fencing is
not lost merely because their descriptive helper now performs a plain read.

Required product E2E remains the primary unchanged-user-behavior gate. The bounded
PostgreSQL integration test supplies concurrency/read-only evidence not observable
through UI alone. It uses existing local test containers and schemas, no live
credentials or optional infrastructure fixture. Missing Docker causes the normal
existing test-fixture skip, which must not be reported as a verification pass.
Record commands, counts and CI SHA; do not deploy to collect evidence.

This is a bounded read-leaf phase, not the entire owner/lifecycle lock-removal design.
