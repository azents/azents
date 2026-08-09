---
title: "External Channel Silent Work Completion Design"
created: 2026-08-09
updated: 2026-08-09
implemented: 2026-08-09
tags: [external-channel, agent, toolkit, backend]
document_role: primary
document_type: design
snapshot_id: channel-260809
---

# External Channel Silent Work Completion Design

- Snapshot: `channel-260809`
- Document reference: `channel-260809/DESIGN`
- Requirements: [channel-260809/REQ](../requirements/channel-260809-silent-work-completion.md)
- ADR: [channel-260809/ADR](../adr/channel-260809-silent-work-completion.md)

## Current Behavior and Requirement Gaps

The Toolkit conditionally selects a schema from continuation binding scope. Mailbox
promotion extracts that scope, worker polling merges or clears it across input types,
the execution loop carries it into each `TurnContext`, and the service/repository
revalidates it. The repository also rejects `ignore` when any task remains pending or
in progress. These mechanisms violate `channel-260809/REQ-1` and
`channel-260809/REQ-3`.

The canonical active-binding validation, active-Work requirement, fieldless ignore
payload, finished transition, and empty provider effect plan already satisfy the
remaining authority and effect boundaries.

## Requirement and ADR Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `channel-260809/REQ-1` | One unconditional Channel Action input model; removal of continuation-scope transport and authorization. |
| `channel-260809/REQ-2` | Existing atomic active-Work finished transition with no provider effects and cleared desired progress. |
| `channel-260809/REQ-3` | Removal of unfinished-task veto from the ignore transition. |
| `channel-260809/REQ-4` | Existing Session, Agent, binding, route, connection, resource, and active-Work validation. |

## Architecture and Ownership

The External Channel binding remains the routing and authorization root. Binding-
specific Toolkit State remains the canonical current/latest Work authority. The Agent's
validated `channel_action` call is the completion decision; model-input provenance is
not an authorization source.

## Toolkit Contract

`ChannelActionInput.mode` is always `finish | continue | ignore`.

- `finish` and `continue` retain their current validators.
- `ignore` requires only `binding` and rejects message, title, task update, and files.
- Tool description states that `ignore` finishes active Work silently and prevents
  further continuation for that Work.

## Runtime and State Transition

The mailbox, worker, execution-loop, adapter, and Toolkit turn contracts stop carrying
continuation binding IDs. External Channel continuation remains a normal mailbox input
kind for scheduling and presentation, but it grants no special Tool capability.

For `ignore`, the repository:

1. validates the active Session, Agent, binding, route, connection, and resource;
2. loads existing binding Work and requires it to be active;
3. marks it finished, advances state and desired-progress revisions, clears desired
   progress, and records `finished_at`;
4. preserves recorded title, tasks, and projection parts; and
5. returns an empty effect plan.

The idle hook lists active Work only, so the finished Work cannot schedule another
External Channel continuation.

## Security and Permissions

No permission is broadened beyond existing Channel Action binding authority. An Agent
can act only on an active binding belonging to its active Session and route. Removing
input provenance eliminates a transient pseudo-authorization source without changing
resource ownership checks.

## Failure and Recovery

Validation and canonical mutation remain transactional. A missing, inactive, or
foreign binding and a missing active Work still fail before mutation. Successful
`ignore` has no provider operation to retry, reconcile, or compensate.

## Test Strategy

- Schema tests verify `ignore` is present without continuation context and remains
  present for initial, continuation, ordinary, and mixed boundary fixtures.
- Toolkit tests verify field validation and service invocation without eligibility
  scope.
- Repository and service tests verify active Work with any task status finishes with no
  effects, while missing active Work and unauthorized bindings still fail.
- Mailbox, worker, execution-loop, and adapter tests remove scope-specific assertions
  and continue verifying input polling and turn behavior.
- Focused backend tests, Ruff, configured type checking, and PR CI provide regression
  evidence. Existing External Channel E2E remains the product integration gate; no new
  fixture credentials are required.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | One unconditional `finish | continue | ignore` schema with no input-provenance authorization | `channel-260809/REQ-1`, `channel-260809/REQ-4`, `channel-260809/ADR-D1` | `decided` |
| M2 | Fieldless ignore atomically finishes existing active Work with no provider effects | `channel-260809/REQ-2`, `channel-260809/REQ-4`, `channel-260809/ADR-D2` | `decided` |
| M3 | Current task status does not veto ignore | `channel-260809/REQ-3`, `channel-260809/ADR-D2` | `decided` |
| M4 | Existing binding and Session resource validation remains authoritative | `channel-260809/REQ-4` | `required` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Conditional Channel Action input models and schema selection | M1 | One unconditional input model | Toolkit model and catalog projection | Schema tests and repository search |
| Continuation binding scope extraction, merge, clearing, transport, and TurnContext fields | M1 | None; normal binding validation remains M4 | Mailbox through worker, engine, adapter, and Toolkit contracts | Type checks, focused tests, and repository search |
| Service/repository ignore eligibility parameter and rejection | M1, M4 | Existing active-binding validation | Channel Action service and repository | Repository tests and search |
| Unfinished-task rejection for ignore | M3 | Explicit terminal Work decision M2 | Repository transition and tests | Pending/in-progress completion tests |
| Continuation-only current Living Spec text | M1, M3 | Current unconditional contract | Toolkit and External Channel flow specs | Spec review and documentation search |
| Implemented historical Requirements, ADRs, and Designs | Project immutability constraint | New `channel-260809` snapshot | No edits to historical files | Git diff confirms historical files unchanged |

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-08-09`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4`
- Approved scope: unconditional External Channel ignore availability, silent active-Work completion regardless of task status, and removal of continuation-only authorization plumbing.
