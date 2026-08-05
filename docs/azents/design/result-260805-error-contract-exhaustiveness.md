---
title: "Result Error Contract Exhaustiveness Design"
created: 2026-08-05
implemented: 2026-08-05
tags: [backend, typing, api]
document_role: primary
document_type: design
snapshot_id: result-260805
---

# Result Error Contract Exhaustiveness Design

- Snapshot: `result-260805`
- Requirements: [result-260805/REQ](../requirements/result-260805-error-contract-exhaustiveness.md)
- ADR: [result-260805/ADR](../adr/result-260805-error-contract-exhaustiveness.md)
- Design reference: `result-260805/DESIGN`

## Current Behavior and Gap

Affected public API, admin API, and service consumers use `match result` followed by `case Failure(error)`. `ty` loses the generic failure-error union at that pattern binding and reports false-positive type assertion failures at otherwise exhaustive `assert_never(error)` arms. Pyright recognizes the same branches as exhaustive.

## Design

### Result consumer boundary

Each of the 116 in-scope Result failure boundaries changes only its outer Success/Failure control flow:

1. Branch on `result.success`.
2. Move the existing Success body to the true branch and read `result.value` there.
3. Move the existing Failure body to the false branch and match `result.error` there.
4. Preserve every existing domain-error arm, response mapping, side effect, return value, and the final `assert_never(result.error)`.

The shared `azcommon.result` runtime contract remains unchanged.

### Interfaces, State, and Operations

- API contracts: unchanged.
- Domain error unions: unchanged.
- Database, broker, runtime, configuration, migration, and observability behavior: unchanged.
- Failure behavior: an unhandled failure remains an assertion failure at the existing exhaustive boundary.

## Test Strategy

This is a static-typing correction with no product behavior change, so no new E2E journey is required. Verification combines:

- a focused static regression test for the `success` discriminator and failure-error match;
- focused existing API and service tests for affected representative route families;
- full backend `ty`, Pyright, and pytest runs;
- PR CI, including existing API/E2E coverage.

## Alternatives and Risks

- The transformation touches many route bodies. Automated structural checks and focused diffs must confirm that every domain-error arm remains unchanged.
- The change intentionally excludes non-Result `assert_never` diagnostics because they have different discriminants and failure models.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Use the existing Result success discriminator before reading the failure error at every in-scope boundary. | `result-260805/ADR-D1` | `decided` |
| M2 | Preserve the current error contracts and exhaustive default arms. | `result-260805/REQ-2`, `result-260805/REQ-3` | `required` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| `match result` Success/Failure wrappers that lose the failure generic in `ty` | `result-260805/ADR-D1` | `result.success` discriminator branch with the existing inner error match | 116 in-scope Result failure boundaries | No scoped `case Failure(error)` type-assertion failure remains in `ty` output. |
| Existing public/admin/service error contracts | None; retained | `result-260805/REQ-2` | Not removed | Focused and full regression tests pass. |

## Design Approval

- Mode: Collaborative
- Decision owner: Requester
- Approved on: 2026-08-05
- Approved Design revision: `1`
- Approved authority IDs: `M1`, `M2`
- Approved scope: Replace only the outer Result Success/Failure control flow at all 116 in-scope failure boundaries, preserving every inner error mapping and exhaustive failure assertion.
