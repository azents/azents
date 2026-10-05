---
title: "Preserve Core Contracts While Restoring Convention Boundaries"
created: 2026-10-05
tags: [backend, conventions, oauth, runtime]
document_role: primary
document_type: requirements
snapshot_id: core-261005
---

# Core Convention Boundaries

## Problem and Primary System Outcome

The pinned core audit at `144c3217e5fa49dcd6f3ba314495d080a6be89d5` identified exception observability and static contract gaps. Restore the established conventions while preserving the existing supported OAuth, MCP, Runtime Profile, and integration-credential behavior.

## Goals

- Preserve valid results and expected invalid-input handling.
- Make unexpected state-processing failures observable.
- Make multi-field result meanings and finite dispatch coverage statically visible.
- Keep supported external-service operations inside their established public SDK boundary.

## Non-goals

- Change Toolkit ownership, authorization, database transaction boundaries, provider capabilities, or token rotation policy.
- Change wire formats, profile schemas, stored state formats, endpoint selection, or integration credential settings.
- Modify the pinned audit checkout or complete the parent audit checkpoint.

## Requirements

### core-261005/REQ-1 — OAuth State Failure Classification

Malformed encoded state, invalid authenticated ciphertext, and invalid decoded state remain rejected. Unexpected runtime or programming failures propagate.

Acceptance: valid state round trips remain unchanged; wrong keys, truncated data, malformed Unicode/JSON are rejected; an injected unexpected runtime failure raises rather than returning an invalid-state result.

### core-261005/REQ-2 — Named Multi-field Contracts

Every confirmed multi-field result exposes explicit field meanings without changing its values or any public serialization.

Acceptance: all six audited multi-field producers and owned callers use declared named fields; OAuth identities, PKCE values, MCP transport choice, constraint sets and coordinator credential validation remain unchanged.

### core-261005/REQ-3 — Runtime Profile Constraint Coverage

Provider compatibility continues to enforce the same finite numeric and string constraints across supported Profile kinds and versions.

Acceptance: declared field access covers every constraint path; numeric bounds, allowed values, optional DIND behavior and incompatibility results retain their current semantics; additions to the finite contract are visible to static checking.

### core-261005/REQ-4 — Integration Secret Coverage

All current integration credential variants produce the same operation-scoped client settings. A new variant requires explicit implementation rather than an unnoticed runtime fallback.

Acceptance: existing six variants retain their settings, and the closed-union fallback is statically exhaustive.

### core-261005/REQ-5 — OAuth Provider Boundary Parity

Authorization-code exchange and refresh use supported SDK operations while preserving their current provider and caller contracts.

Acceptance: public and confidential client authentication, PKCE, resource indicators, configured proxy routing, successful token decoding, omitted refresh tokens, HTTP errors and HTTP-200 provider errors are covered by focused tests. No private SDK API or undocumented direct-provider exception is introduced.

## Fixed Constraints and Authority

Current convention bodies and current Living Specs establish the intended corrections. The coordinating requester explicitly assigned these bounded fixes in isolated WT8 and required Requirements before code, current Spec review, native full type checks, focused tests and hooks. Root owns review and PR creation; this task does not push.

## Open Assumptions

The installed OAuth SDK uses a distinct HTTP exception family. Migration must preserve existing caller classification rather than silently changing which failures are handled. Any unsupported public capability or material behavior decision is separately reported before implementation.

## Requester Confirmation

The coordinating request on 2026-10-05 authorizes the bounded outcome above; it does not authorize a new product behavior or a change to the parent audit scope.
