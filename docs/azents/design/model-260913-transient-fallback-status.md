---
title: "Transient Model Fallback Status Design"
created: 2026-09-13
updated: 2026-09-13
tags: [model, fallback, frontend, backend]
document_role: primary
document_type: design
snapshot_id: model-260913
---

# Transient Model Fallback Status Design

- Snapshot: `model-260913`
- Requirements: [`model-260913/REQ`](../requirements/model-260913-transient-fallback-status.md)
- ADR: [`model-260913/ADR`](../adr/model-260913-transient-fallback-status.md)

## Current Behavior and Gap

The composer performs a Session availability query whenever model selection is enabled. Its desktop Popover and mobile Drawer always reserve space for a Model availability section and may expose cooldown, fallback, countdown, refresh, reserve, and cancel states. This persists independently of whether a Run is active.

The active Run already owns the authoritative prepared `SessionInferenceState`, whose `applied_model_route.candidate_role` identifies Primary versus fallback. That route is not currently projected into `ChatLiveRunState`.

## Architecture and Flow

1. Extend the live Run domain and public response with required boolean `using_fallback`.
2. The Worker computes the value from the currently prepared foreground route before every live Run publication.
3. REST live-state reconstruction computes the same value from the Session inference snapshot.
4. The Web live decoder maps the field to `ChatLiveRunState.usingFallback`.
5. `ChatInput` renders the existing compact localized `Fallback` badge only when the current live Run reports `usingFallback=true`.
6. Remove the Web availability query, reservation mutations, timer, picker panel, supporting state module, stories, tests, and tRPC procedures.

The badge disappears through the existing live Run clear/reset path. No separate timer, cache, or availability invalidation owns this state.

## Interfaces and Data

`ChatLiveRunStateResponse` adds:

- `using_fallback: bool` — true only when the current prepared foreground route has candidate role `fallback`.

No database schema or persistent public availability contract changes in this snapshot.

## Failure and Recovery

A missing or invalid live Run projection fails closed to no fallback badge. REST reload reconstructs the boolean from persisted Session inference state for a still-active Run. WebSocket updates replace the value when candidate progression republishes the live Run, and normal live Run removal clears it.

## Test Strategy

- Backend unit tests cover Primary and fallback live projection from Worker publication and REST reconstruction.
- Public chat response contract tests cover the required boolean field.
- Web decoder tests cover true, false, and invalid/missing input.
- Component/container tests verify no availability query or controls remain and the compact badge follows only active Run state.
- The quota-fallback browser E2E is narrowed to observe the temporary active fallback badge and its disappearance after terminal completion; it no longer reserves or cancels Primary.
- Required CI remains credential-free and owns the complete user-visible regression.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Persistent `ModelAvailabilityControl` panel | `model-260913/REQ-2` | Compact active Run fallback badge | Web component and picker composition | Source grep, Storybook/test removal, browser assertion |
| Web availability query, refresh timer, and reservation mutations | `model-260913/REQ-2` | Live Run subscription already used by the composer | Container and tRPC procedures | No generated availability calls in Web source |
| Cooldown-derived fallback badge | `model-260913/REQ-1`, `model-260913/ADR-D1` | `ChatLiveRunState.using_fallback` | Live domain, API response, decoder, ChatInput | Primary/fallback/terminal tests |
| Backend availability and reservation contracts | None in this snapshot | Existing backend behavior | Not removed | Explicit non-removal audit |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Required active Run `using_fallback` projection | `model-260913/REQ-1`; `model-260913/ADR-D1` | `decided` |
| M2 | Remove persistent availability and recovery UI path | `model-260913/REQ-2`; `model-260913/ADR-D2` | `decided` |
| M3 | Preserve automatic candidate progression and internal cooldown/probe behavior | `model-260913/REQ-3`; current fallback Specs | `existing` |

## Feasibility

- `model-260913/REQ-1`: feasible — candidate role already exists in the prepared Session route and live Run publication occurs after quota progression.
- `model-260913/REQ-2`: feasible — all standing availability UI state is isolated to the chat input container, picker component, and tRPC procedures.
- `model-260913/REQ-3`: feasible — the correction does not modify model operation selection or failure progression.

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-09-13`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3`
- Approved scope: show a temporary fallback status only during an active fallback Run and remove the standing availability/recovery UI without changing automatic fallback behavior.
