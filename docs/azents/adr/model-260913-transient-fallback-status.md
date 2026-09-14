---
title: "Transient Model Fallback Status"
created: 2026-09-13
tags: [model, fallback, frontend, architecture]
document_role: primary
document_type: adr
snapshot_id: model-260913
---

# Transient Model Fallback Status ADR

- Snapshot: `model-260913`
- Requirements: [`model-260913/REQ`](../requirements/model-260913-transient-fallback-status.md)

## Context

The deployed model picker derives a persistent availability and recovery surface from Workspace cooldown state. `model-260913/REQ-1` and `model-260913/REQ-2` instead limit the user-visible status to the interval in which the current active Run is actually using a fallback candidate.

## Decisions

### model-260913/ADR-D1: Use active Run state as the only fallback-status authority

The live Run projection carries whether its current foreground model route uses a fallback candidate. The Web composer renders the compact status directly from that projection and clears it when the live Run disappears or reports Primary use.

A standing availability query is rejected because cooldown is not equivalent to an active fallback Run and keeps status visible outside the confirmed scope. Inferring fallback from display names is rejected because labels and physical model names are not routing roles.

### model-260913/ADR-D2: Remove the persistent availability UI path without changing backend fallback authority

The Web application removes its availability query, recovery mutations, picker panel, countdown, and Primary recovery actions. Ordered candidates, automatic quota progression, Workspace cooldown/probe state, and existing backend contracts remain unchanged in this corrective snapshot.

Removing backend availability and reservation contracts is rejected for this snapshot because the requester confirmed the status-display boundary, not a persistence or public-API migration. That removal requires separate explicit product authority.

## Consequences

- The user-visible state exactly follows the active Run rather than retained cooldown state.
- Reload and WebSocket resync remain consistent because both reconstruct the live Run projection.
- Existing backend availability and reservation code becomes unused by the Web application but is not silently removed under a UI-only correction.
