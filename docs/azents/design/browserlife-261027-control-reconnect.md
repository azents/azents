---
title: "Browser Continuity Across Control Reconnection Design"
created: 2026-10-27
tags: [browser, runtime, reliability, security]
document_role: primary
document_type: design
snapshot_id: browserlife-261027
---

# Browser Continuity Across Control Reconnection Design

Authority: [Requirements](../requirements/browserlife-261027-control-reconnect.md)
and [decisions](../adr/browserlife-261027-control-reconnect.md).

## Current Behavior and Scope

The reconnect loop owns controller, native manager and viewer. Closing connection
operations retires native resources. A loop-captured generation getter prevents
simply moving construction. Live scope bool conflates connection loss and access
revocation. Existing UI reconnect tests replace only the viewer socket.

This fix retains native state only within one Runner process and one browser
intent. It changes no shell/PTY reconnection policy, profile storage or site policy.

## Design Authority

- Design revision: `1`

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Process-owned controller/native resources; connection-only operation cleanup | REQ-1, REQ-5, ADR-D1 | decided |
| M2 | Stable nullable current epoch, transport-loss fence and old-work cleanup barrier | REQ-2, REQ-3, ADR-D1 | decided |
| M3 | Retain current intent transitions and reconcile readiness in fresh generation | REQ-1, REQ-2, current Session Browser Spec | derived |
| M4 | Typed live authority outcomes and existing transient/denied/expiry/target codes | REQ-4, REQ-6, ADR-D2 | decided |
| M5 | Cleanup uncertainty blocks browser until explicit intent retirement succeeds | REQ-2, REQ-3, ADR-D3 | decided |
| M6 | No replay; fresh observation, attachment and current input evidence | REQ-2, REQ-3, current Session Browser Spec | existing |

## Ownership and Lifecycle

Create controller once outside the reconnect loop. Bind it and native managers to
one stable generation callback. The callback requires both a live transport and a
current RunLoop registration. The transport marks itself unavailable synchronously
on stream termination; RunLoop clears accepted authority before cancellation drain.
These fences precede asynchronous cleanup. No native resource is recreated solely
because generation changed.

Connection cleanup cancels/joins old controller commands and viewer attachments,
closes frame sources, cancels outstanding page.pending dispatch, disposes old
observation handles and clears transient popup ownership. Native contexts, pages,
Session bindings, surviving task/page/incarnation, browser input key and profile
bytes remain. Native dialogs are never automatically accepted/dismissed. Already
sent effects remain uncertain and are never replayed. New registration cannot
begin before this barrier completes. Final process shutdown owns native close.

Controller configuration transitions stay shielded and serialized independently
of response connections. Connection suspension coordinates with transition locking
without canceling authoritative application. Reconciliation queries retained status;
same intent ready/failed/applying does not restart. An offline intent replacement
continues ordinary browser-only retirement before new native resources are used.

Cleanup SDK failure exposes failed browser_cleanup_failed evidence and keeps
commands fail-closed. It does not silently replace the browser. An explicit new
intent can attempt normal retirement; unconfirmed retirement retains the existing
sticky failure boundary. Resource shutdown must still release display/driver.

## Interfaces and Security

Replace live validation bool with closed internal authority results: current,
unavailable, revoked, expired. API maps unavailable to existing transient 4500,
revoked to 4403, expiry to 4408. Actual native target closure remains 4409. Owner
checks current before effects and rejects every other result. Initial admission
and post-admission revalidation follow the same separation. Unclassifiable checks
remain fail-closed. No protobuf, public schema or wire version changes.

UI reuses its current bounded fresh-admission retries. No input or navigation is
replayed. Do not mark surviving targets unavailable or resources denied from epoch
loss. Real access revocation and expiry still suppress content/input.

Tool errors distinguish unavailable transport and stale connection authority without
claiming physical recreation. Existing Session isolation, source ACKs, exact native
target checks and confidential input process-key ownership remain unchanged.

## Data, Migration and Operations

No DB migration, durable recovery state, profile export, counter or compatibility
fallback. New Runner image is required; server-only rollout cannot change old
Runner cleanup ownership. Initial Runner replacement can terminate old live tabs.
Verify same-process Control-only rollout separately. Rollback restores former
behavior; it cannot resurrect lost pages. Log only bounded content-free lifecycle
information through existing logger integration, never page/input/auth contents.

## Removal and Replacement

| Existing behavior | Authority | Replacement | Boundary | Verification |
| --- | --- | --- | --- | --- |
| Loop-owned controller/native manager | REQ-1, ADR-D1 | Process owner | Runner entrypoint | Real reconnect test |
| Operation close implicitly closes browser | ADR-D1 | Separate connection drain and final close | Runner operations/controller | Cleanup tests |
| Per-loop captured native generation | REQ-2, ADR-D1 | Stable current live epoch callback | Runner/transport | Stale epoch tests |
| Boolean live scope and epoch-as-target failure | REQ-4, ADR-D2 | Typed authority classification | API/Owner | Authority/socket tests |
| Ambiguous replacement diagnosis | REQ-6 | Unavailable/changed connection errors | Engine tools | Tool tests |
| Connection-scoped Spec ownership | REQ-1 | Process resource/connection authority ownership | Living Spec | Spec review |

Persisted configuration/profile state and public/generated clients remain unchanged.
Tests that assumed operation close owns native resources must instead close their
explicit process owner. Historical implemented documents remain immutable.

## Test Strategy

One minimal real Control-reconnect product journey retains a synthetic in-page
memory canary and resource identity then accepts fresh input. Use isolated existing
Docker fixture infrastructure; never restart a session-shared Control blindly.
No external website, account or CAPTCHA prerequisite. Use registration/projection
barriers instead of fixed waits. Existing viewer reconnect coverage remains useful
but cannot establish Control continuity.

Lower native tests exercise both engines, epoch/ref rejection, dialog pending,
viewer held-state cleanup, engine transitions during loss, repeated reconnect and
final shutdown. API/Owner/tool/UI contract tests cover transient versus actual
denial/expiry/target loss and preserve no-replay. Ruff, configured type checks and
relevant pytest run locally; final SHA CI is required. Missing native prerequisites
are failures to prepare, not successful verification or blanket skips.

Evidence records distinguish fake-manager, native SDK, integrated transport and
product E2E results. No real-site authentication guarantee is inferred. Only
regression-critical combinations enter E2E; remaining matrices stay below it.

## Authority and Feasibility

Each REQ maps to M1-M6; each mechanism is authorized above. Existing manager/context
ownership and current-intent coordinator support implementation without new state.
Risks are stream-loss timing, pending SDK/dialog behavior and attachment cleanup
races. Validate those paths before declaring implementation complete. Local fake
manager evidence establishes current closure and same-intent idempotence only.

## Design Approval

- Mode: Autonomous
- Decision owner: `/root/design-owner`
- Approved on: 2026-10-27
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5, M6`
- Approved scope: process-owned native browser, connection authority retirement,
  existing intent reconciliation, typed failure classification, fail-closed cleanup
  and no replay. Authority audit passed; source-grounded feasibility accepted with
  native/transport/product verification required before delivery. Effect tasks
  must be canceled synchronously at detected transport loss or recheck epoch
  immediately before effects after intervening awaits.
