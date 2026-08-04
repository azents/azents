---
title: "Backend ty Migration Analysis"
created: 2026-08-04
tags: [backend, python, typing, migration]
status: research-note
---

# Backend ty Migration Analysis

This note records the initial `ty` baseline for `python/apps/azents`, the observed
diagnostic taxonomy, and a proposed migration order. It is an implementation
tracking input, not a product specification or an approved architecture decision.

## Baseline

The baseline was collected from commit `09455f796` after the Runtime Control typed
protobuf work:

```console
cd python/apps/azents
uv run ty check --error-on-warning
```

The command reported 948 diagnostics: 943 errors and 5 warnings.

| Diagnostic | Count | Primary pattern |
| --- | ---: | --- |
| `invalid-argument-type` | 559 | Strict model, fixture, function, and gRPC call inputs |
| `type-assertion-failure` | 118 | Closed result unions not narrowed to `Never` before `assert_never` |
| `unresolved-attribute` | 93 | Async iterator capabilities and incomplete third-party typing |
| `invalid-assignment` | 47 | Test doubles, monkeypatches, and broad `object` values |
| `invalid-return-type` | 39 | Unvalidated JSON or dynamic data returned as typed containers |
| `invalid-type-form` | 33 | Class `list` members shadowing the builtin generic |
| `not-subscriptable` | 18 | Dynamic values inferred as `object` before indexing |
| `invalid-await` | 10 | Redis methods typed as synchronous-or-asynchronous unions |
| `invalid-key` | 10 | Dynamic string keys used against `TypedDict` |
| Other | 21 | Callable, overload, cast, yield, import, override, and iteration issues |

The three largest categories account for 770 diagnostics, approximately 81 percent
of the baseline.

## Concentration

The largest file-level concentrations were:

| File | Diagnostics |
| --- | ---: |
| `src/azents/engine/events/execution_test.py` | 106 |
| `src/azents/api/public/chat/v1/chat_api_test.py` | 100 |
| `src/azents/runtime/control_protocol/grpc/runner_server_test.py` | 62 |
| `src/azents/runtime/control_protocol/grpc/runner_transfer_server_test.py` | 31 |
| `src/azents/api/public/chat/v1/__init__.py` | 30 |
| `src/azents/runtime/control_protocol/grpc/runner_transfer_grpc_integration_test.py` | 29 |

## Proposed Migration Order

1. Remove mechanically provable diagnostics:
   - Qualify builtin collection generics when class members shadow their names.
   - Remove genuinely redundant casts.
   - Correct local stubs where the runtime interface is already known.
2. Correct shared test fixtures and typed builders that produce the bulk of
   `invalid-argument-type` diagnostics.
3. Preserve exhaustive API result handling while making union narrowing explicit.
4. Model async stream capabilities and third-party interfaces through accurate
   annotations, protocols, or local stubs.
5. Validate dynamic JSON and external API data at system boundaries.
6. Correct test doubles, monkeypatch signatures, and remaining isolated diagnostics.
7. Switch backend CI and pre-commit enforcement from Pyright to `ty` only after
   `ty check --error-on-warning` is clean.

## Phase 1: Builtin Generic Qualification

The first mechanical phase addresses all 33 `invalid-type-form` diagnostics. Python
class scopes bind method names, so a method named `list` can shadow the builtin
`list` used by later annotations in that class. Using `typing.List[...]` for those
colliding annotations preserves runtime behavior and keeps the intended generic
distinct from the class member.

The same phase removes four casts that `ty` proves are redundant without changing
the inferred type or runtime value.

Pyright remains the enforced backend checker during this phase. Generated protobuf
and gRPC files remain untouched.

### Phase 1 Result

The phase reduces the baseline from 948 to 911 diagnostics:

- `invalid-type-form`: 33 to 0
- `redundant-cast`: 4 to 0
- Pyright: 0 errors
- Backend tests: 3,883 passed

The remaining diagnostics require typed fixture correction, union narrowing,
third-party interface modeling, or dynamic-data validation and are intentionally
outside this mechanical phase.

## Phase 2: Test Narrowing and Stream Cleanup

The second phase starts from `main` commit `bb803e99f`, where unrelated merged work
increased the baseline from 911 to 913 diagnostics.

This phase:

- Narrows dynamic dictionaries, list elements, strings, and callable factories in
  tests before using their typed operations.
- Uses shared TypeGuard helpers for reusable string-keyed dictionary and factory
  checks.
- Closes Runtime Control test streams through a helper that verifies the concrete
  value is an `AsyncGenerator` before calling `aclose()`.
- Preserves the production gRPC interface as `AsyncIterator`; generated protobuf and
  gRPC files remain unchanged.

### Phase 2 Result

The phase reduces the current-main baseline from 913 to 862 diagnostics:

- Runtime Control stream `aclose` diagnostics: 27 to 0
- Test-only `not-subscriptable` diagnostics: 16 to 0
- `call-non-callable` diagnostics: 6 to 0
- `unsupported-operator` diagnostics: 1 to 0
- Pyright: 0 errors
- Targeted tests: 402 passed
- Backend tests: 3,889 passed

The two remaining `not-subscriptable` diagnostics are production validation issues
in `runtime_provider_contract.py` and remain outside this test-focused phase.
