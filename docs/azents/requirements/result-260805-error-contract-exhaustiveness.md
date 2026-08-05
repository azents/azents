---
title: "Result Error Contract Exhaustiveness Requirements"
created: 2026-08-05
updated: 2026-08-05
implemented: 2026-08-05
tags: [backend, typing, api]
document_role: primary
document_type: requirements
snapshot_id: result-260805
---

# Result Error Contract Exhaustiveness Requirements

- Snapshot: `result-260805`
- Document reference: `result-260805/REQ`

## Problem

Backend maintainers cannot use `ty` output to identify newly unhandled domain errors at Result boundaries because existing Success/Failure exhaustive branches produce false-positive type assertion failures.

## Primary Actor

Azents backend maintainer.

## Primary Scenario

A backend maintainer runs the backend type checker after a domain operation returns a Result. Existing success and failure branches retain their current runtime behavior, and the type checker recognizes the branch as exhaustive when every declared failure is handled.

## Supporting Scenarios

- Public and admin API routes retain their exact current HTTP status codes, response bodies, and domain-error mappings.
- Service-layer Result consumers retain their current success paths, failure propagation, side-effect ordering, and recovery behavior.

## Goals

- Remove all current `ty` type-assertion failures caused by the `azcommon.result.Result` Success/Failure exhaustiveness pattern.
- Preserve exhaustive checking so a genuinely unhandled declared failure remains detectable.

## Non-Goals

- Changing any public or admin API contract, HTTP status code, response body, or error message.
- Changing domain-error membership, service behavior, persistence, broker behavior, retry behavior, or authorization.
- Fixing unrelated `assert_never` diagnostics for action enums, state machines, or non-Result unions.
- Suppressing diagnostics with casts, type ignores, broad fallback branches, or checker-only runtime behavior.

## Requirements

### REQ-1. Result failure exhaustiveness

The backend type checker must recognize exhaustive Success/Failure handling for every current Result-boundary diagnostic in scope.

**Acceptance criteria**

- The current 116 `ty` `type-assertion-failure` diagnostics at `assert_never(error)` Result failure branches are absent.
- The scope covers public API, admin API, and service consumers that use the shared Result pattern.
- Unrelated non-Result `assert_never` diagnostics remain out of scope.

### REQ-2. Existing error contracts

Each affected operation must preserve its observable success and failure contract.

**Acceptance criteria**

- Existing public and admin route status codes, response bodies, and domain-error mappings are unchanged.
- Existing service outcomes, side-effect ordering, authorization behavior, and recovery behavior are unchanged.
- Existing route and service tests continue to pass.

### REQ-3. Exhaustive failure detection

The correction must retain an explicit exhaustive boundary for declared Result failures.

**Acceptance criteria**

- A newly introduced unhandled declared failure is still rejected by static checking or a focused static regression fixture.
- The implementation adds no unchecked casts, type ignores, broad fallback error mapping, or compatibility fallback.

## Fixed Constraints

- The baseline is the 2026-08-05 `main` measurement of 264 `ty` diagnostics, including 116 Result failure exhaustiveness diagnostics.
- Scope is limited to Python backend and the shared `azcommon.result` contract when necessary.
- The work is delivered as an independent PR and is not merged without explicit requester approval.

## Open Assumptions

- The selected correction can be made at a shared typing boundary or a small number of equivalent boundaries without changing runtime Result semantics.

## Confirmation

Confirmed by the requester on 2026-08-05 before ADR and design decisions began.
