---
title: "Discord Tracker Title-List Relocation Design"
created: 2026-10-07
implemented: 2026-10-07
tags: [discord, external-channel, activity-tracker, backend]
document_role: primary
document_type: design
snapshot_id: tracker-261007
---

# tracker-261007/DESIGN: Discord Tracker Title-List Relocation

- Requirements: [tracker-261007/REQ](../requirements/tracker-261007-title-list-relocation.md)
- Decision: [tracker-261007/ADR-D1](../adr/tracker-261007-title-list-relocation.md#d1-use-the-ordered-task-title-list-as-the-relocation-criterion)

## Current Behavior and Replacement

`ExternalChannelWorkRepository.commit_direct_action` owns canonical task replacement
and detached ordered provider-effect planning. Replace the full-task comparison and
message-presence gate with comparison of ordered task titles before canonical tasks
are replaced. Restrict relocation to Discord `continue` and `request_input`, as before.

The existing relocation branch deletes a standalone host or clears the Tracker from
a reply host, then creates a notification-suppressed standalone replacement. Creation
depends on confirmed removal. Append requested replies after this branch; message-free
updates have no reply effects. An unchanged title list takes the existing create/update
branch and preserves host identity. A work-title-only update also retains the host.

No API, schema, permission, connection policy, stored revision, configuration, migration,
or provider adapter changes are required. Existing Work CAS, exact cycle/revision
revalidation, transient effect dependencies, ambiguous-outcome handling, and later
explicit progress convergence remain the authority for concurrency and failures.

## Design Authority

- Design revision: `1`

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Relocate for ordered title-list changes independently of message presence | REQ-1, REQ-2, ADR-D1 | required |
| M2 | Reuse removal-before-create, reply-host detachment, silent create, retained-host update and failure boundaries | REQ-3; current external-channel-delivery Activity Tracker Lifecycle | existing |

Both requirements map directly to M1; lifecycle preservation maps to M2. No additional
product mode or material technical decision is introduced. Equivalent list extraction,
local variable naming, and parameterized test composition are implementation details.

## Removal and Replacement

| Existing behavior | Authority | Replacement | Boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Message-gated, full-task relocation predicate | REQ-1, REQ-2; ADR-D1 | M1 title-list criterion | Canonical Action transition | Diff and parameterized regression matrix |
| Message-free title changes edit retained host | REQ-1 | Existing relocation path M2 | Projection effect planning | No-message rename/add/remove/reorder tests |
| Current Spec text describing old policy | REQ-1, REQ-2 | Updated flow/domain/toolkit Specs | Same PR | Spec review and catalog validation |

Historical snapshots stay immutable. No state, fixture, configuration, generated
client, provider integration, or legacy fallback removal is necessary.

## Feasibility

Feasibility: **feasible**. Canonical validated titles and the pre-transition task list
already exist in the transition; both projection branches already support standalone
and reply hosts. No external service capability change is needed.

## Test Strategy

Primary behavioral matrix covers standalone/reply hosts and `continue` with/without
a message plus `request_input`: unchanged titles, completion, reopening, comments,
sources, IDs and overall title must update; rename/add/remove/reorder must recreate.
Assert operations, retained message identity, dependency ordering and canonical tasks.
Existing service tests cover cleanup failure, reply independence and provider delivery.
Slack and finish/ignore regression tests remain included.

For this focused provider-planning change, deterministic repository and provider-adapter
unit tests are the acceptance evidence. Live Discord E2E is not claimed: it requires a
separate approved participant/Bot conversation and real provider mutations, which are
outside this PR verification scope. No new testenv fixture, seed, or credential is
required. Optional live tests must not silently stand in for deterministic checks.
Run focused pytest, Ruff, whole-backend ty, documentation validation, commit hooks and
required CI; retain exact counts and command outcomes in the PR report. No deployment
or live credential validation is performed.

## Rollout and Risks

One focused PR, no migration. Runtime behavior changes only when that code is deployed;
merge and deployment require separate authorization. Reverting the PR restores the
old predicate. Existing projection ambiguity and temporary absence during replacement
remain unchanged; no durable retry work is added.

## Design Approval

- Mode: Collaborative, scoped direct implementation request.
- Decision owner: Requester.
- Authorized on: 2026-10-07.
- Scope: title-list-only recreation policy M1 and unchanged lifecycle M2, revision 1.
- Authority IDs: `M1`, `M2`.
- The request explicitly authorizes the behavior change; this record does not claim a
  separate review or approval of this document. No additional material choice is made.
