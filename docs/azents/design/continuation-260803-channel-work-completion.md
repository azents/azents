---
title: "External Channel Continuation Work Completion Design"
created: 2026-08-03
implemented: 2026-08-04
tags: [external-channel, agent, backend]
document_role: primary
document_type: design
snapshot_id: continuation-260803
---

# External Channel Continuation Work Completion Design

- Snapshot: `continuation-260803`
- Requirements:
  [`continuation-260803/REQ`](../requirements/continuation-260803-channel-work-completion.md)
- ADR:
  [`continuation-260803/ADR`](../adr/continuation-260803-channel-work-completion.md)
- Design reference: `continuation-260803/DESIGN`

## Scope

This design narrows PR #1129 to continuation-owned Channel Work completion. The
Toolkit State migration already delivered by PR #1123 remains unchanged.

## Mechanisms

### Continuation scope

Mailbox promotion returns `external_channel_continuation_binding_ids`:

- `None` for no eligible model-input boundary;
- an empty set for eligible non-continuation input; and
- the validated `active_bindings` set for `external_channel_continuation`.

Run input polling merges multiple promoted items conservatively. Two non-empty
continuation sets are unioned. Any empty scope in the same boundary clears the merged
scope. The execution loop replaces its active scope only when polling returns a
non-`None` value, preserving scope across Tool-only follow-up.

### Toolkit and service authorization

`TurnContext` carries the active continuation binding set. The External Channel
Toolkit uses the ordinary `finish | continue` schema for an empty set and adds
`ignore` for a non-empty set. The service receives the same set and rejects an
`ignore` binding outside it.

### Canonical transition

The existing binding-specific Toolkit State mutator rejects `ignore` while a task is
`pending` or `in_progress`. Otherwise it finishes the Work, advances existing
revisions, clears desired progress, retains current provider projection observation,
and returns an empty provider-effect plan.

### Prompt placement

The static prompt only states the publication boundary and that `ignore` may be
available during `external_channel_continuation` to end Work without external
publication. It adds no relevance, opt-out, or general response-selection policy.
Mode constraints remain in the Tool description and schema.

## Test Strategy

### Deterministic integration matrix

Backend integration tests are the primary acceptance evidence because the product
contract is a capability and canonical-state transition inside the run boundary.
They cover:

- initial External Channel invocation, ordinary input, and mixed input clearing the
  continuation scope;
- one or multiple continuation items carrying only their binding handles;
- Tool-result follow-up retaining the scope and new actionable input replacing it;
- conditional `ignore` schema exposure and binding-specific service authorization;
- successful completion for empty or terminal-only task lists;
- rejection before mutation for `pending` or `in_progress` tasks; and
- zero provider effects, unchanged provider projection observation, and no later idle
  continuation for completed Work.

### E2E policy

No new model-driven E2E is authoritative for this snapshot. Whether a sampled model
chooses `ignore` is nondeterministic, while the existing deterministic E2E fixtures
cannot directly invoke a continuation-scoped tool choice without replacing the
behavior under test with a proxy. The superseded selective-response proxy E2E is
therefore removed rather than retained as false product evidence.

Existing deterministic External Channel journeys remain the regression gate for
invocation, progress, final delivery, and continuation scheduling. The focused
backend integration matrix is the acceptance gate for the new silent-completion
contract, and the full backend and deterministic E2E CI lanes must pass. No live
provider credentials are required.

## Verification

- Mailbox tests prove only continuation items produce a non-empty scope.
- Executor tests prove mixed actionable input clears the scope.
- Execution tests prove Tool follow-up preserves scope and new input replaces it.
- Toolkit tests prove conditional schema exposure and fieldless binding authorization.
- Repository and service tests prove unfinished-task rejection, finished Work state,
  empty outcomes, and zero provider effects.

## Requirement Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `continuation-260803/REQ-1` | M1, M2 |
| `continuation-260803/REQ-2` | M2, M3, M4 |
| `continuation-260803/REQ-3` | M3 |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Carry an ephemeral continuation binding set through mailbox promotion, run polling, and Tool-result follow-up, and clear it on other actionable input. | `continuation-260803/REQ-1`, `continuation-260803/ADR-D1` | `decided` |
| M2 | Expose and authorize `ignore` only for bindings in the active continuation set. | `continuation-260803/REQ-1`, `REQ-2`, `continuation-260803/ADR-D1` | `decided` |
| M3 | Finish only active Work with no pending or in-progress task, clear desired progress, and return no provider-effect plan. | `continuation-260803/REQ-2`, `REQ-3` | `required` |
| M4 | Limit prompt guidance to continuation Work completion and keep ordinary publication behavior unchanged. | `continuation-260803/REQ-1`, `REQ-2`, `continuation-260803/ADR-D1` | `derived` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Generic `TurnProvenance` model and ordinary/external/mixed turn classification | M1 | Continuation binding scope derived directly from typed mailbox items | Core type, execution propagation, and tests | Production and focused-test source scan contains no `TurnProvenance` implementation |
| Initial-invocation and ordinary-turn selective-response eligibility | M2, M4 | `finish \| continue` outside continuation; continuation-scoped `ignore` only | Toolkit schema, prompt, service authorization, and specs | Schema and executor tests prove initial, ordinary, and mixed boundaries have an empty scope |
| Selective-response proxy E2E | M1, M2 | Deterministic backend integration matrix plus existing External Channel journey regression coverage | Testenv E2E test and PR test plan | Deleted proxy test is absent and focused backend tests cover the canonical contract |
| Temporary `channel-260803` phase plans | Snapshot cleanup | Implemented Requirements, ADR, Design, and Living Specs | `docs/azents/plans/` | Feature-specific plans are absent from the final diff |

## Feasibility

- M1 is feasible because mailbox items already distinguish
  `external_channel_continuation` and carry active binding handles.
- M2 is feasible because Toolkit State is rebuilt for every model call and the service
  already validates Session and binding authority.
- M3 is feasible within the existing binding-specific Toolkit State mutation, which
  serializes canonical Work changes and can return an empty effect plan.
- M4 is a local schema and guidance change with no provider or persistence dependency.

No implementation blocker or unresolved material decision remains.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-08-03`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4`
- Approved scope: continuation-owned binding capability, Toolkit and service
  authorization, silent canonical Work completion, removal of generic
  selective-response machinery, and deterministic verification.
