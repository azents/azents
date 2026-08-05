---
title: "Result Error Contract Exhaustiveness ADR"
created: 2026-08-05
tags: [backend, typing, api]
document_role: primary
document_type: adr
snapshot_id: result-260805
---

# Result Error Contract Exhaustiveness ADR

- Snapshot: `result-260805`
- Requirements: [result-260805/REQ](../requirements/result-260805-error-contract-exhaustiveness.md)

## D1. Narrow Result consumers through the success discriminator

- Status: Accepted
- Decision owner: Requester
- Date: 2026-08-05
- Affects: `result-260805/REQ-1`, `result-260805/REQ-2`, `result-260805/REQ-3`

### Decision

At each in-scope `azcommon.result.Result` consumer, branch on the existing `success: Literal[True] | Literal[False]` discriminator before reading the success value or failure error. Preserve the existing failure-error `match` arms and call `assert_never(result.error)` in the final failure arm.

### Consequences

- `ty` retains the concrete `Failure[F]` error union in the failure branch.
- Pyright and `ty` both preserve the explicit default-arm exhaustiveness check.
- Runtime Success/Failure behavior, error mapping, and side-effect order remain unchanged.

### Rejected alternatives

- Changing only the shared `Result` type alias: a minimal reproduction still leaves `Failure(error)` pattern bindings as `Unknown` in `ty`.
- Adding only a `TypeIs` failure helper: the generic parameter is retained, but `ty` still does not treat the class-union error match as exhausted.
- Casts, type ignores, diagnostic suppression, or broad fallback mapping: prohibited by `result-260805/REQ-2` and `result-260805/REQ-3`.
