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

## Phase 3: Runtime Control gRPC Test Doubles

The third phase makes Runtime Control gRPC test doubles satisfy the interfaces they
model instead of relying on checker suppressions or incomplete structural fakes.

This phase:

- Adds a reusable typed `grpc.aio.ServicerContext` fake for direct-call tests.
- Completes Runner control, coordination, transfer-result, and object-store test
  doubles against their production protocols.
- Returns real `S3VerifiedObject` values from transfer object-store fakes.
- Narrows dispatch and download-result unions before accessing variant fields.
- Preserves generated protobuf/gRPC outputs and production service interfaces.

### Phase 3 Result

The phase reduces the baseline from 862 to 745 diagnostics:

- Runtime Control gRPC test diagnostics: 117 to 0
- Pyright: 0 errors
- Targeted tests: 74 passed

One precise `ty` suppression remains at a generated gRPC stub construction boundary.
The generated overload correctly returns an async stub for an aio channel, which
Pyright recognizes, while `ty` selects the synchronous overload.

## Phase 4: Native Request Inspection Variance

The fourth phase corrects the generic upper bound used by `AgentRunExecution`.
`NativeRequestInspection` declared `model` as writable even though execution only
reads it and native request models expose frozen values. Declaring the inspection
surface as a read-only property accurately models that contract.

### Phase 4 Result

The phase reduces the baseline from 745 to 637 diagnostics:

- `execution_test.py` generic-bound diagnostics: 108 to 0
- Pyright: 0 errors
- Targeted tests: 54 passed

The production `AgentRunExecution` generic shape and runtime behavior remain
unchanged.

## Phase 5: Chat API Test Doubles

The fifth phase makes Chat API service doubles explicitly satisfy the concrete
dependencies and broker protocol used by the public route helpers.

This phase:

- Completes the in-memory broker against the full `SessionBroker` lifecycle
  surface, including keyword-compatible parameter names.
- Makes WebSocket broadcast, Chat session, Chat write, AgentSession input,
  worktree cleanup, and Skill state doubles inherit the dependencies they model.
- Aligns overridden result types with the complete production error unions while
  preserving each test's configured runtime result.

### Phase 5 Result

The phase reduces the baseline from 637 to 537 diagnostics:

- `chat_api_test.py` diagnostics: 100 to 0
- Targeted `ty` check: passed

The production Chat API behavior and dependency interfaces remain unchanged.

## Phase 6: Small Typed Boundary Cleanup

The sixth phase groups isolated diagnostics that can be corrected without changing
product behavior or result-union policy.

This phase:

- Narrows dynamic dictionaries and optional Mock call records in tests before
  accessing their typed members.
- Aligns test monkeypatch signatures with the methods they replace.
- Builds canonical Runtime Provider Profile payloads from validated Pydantic models.
- Narrows SQLAlchemy DML results to `CursorResult` before reading `rowcount`.
- Supports both synchronous test doubles and asynchronous Redis client return values
  at two typed boundaries.

### Phase 6 Result

The phase reduces the baseline from 537 to 495 diagnostics:

- Changed-file `ty` check: passed
- Pyright: 0 errors
- Targeted tests: 452 passed
- Migration tests: 8 passed
- Backend tests: 3,902 passed

The remaining diagnostics require larger result-union narrowing, service-double
completion, external-library typing, or dynamic-data validation work.

## Current-Main Category Baseline

Subsequent merged mechanical cleanup reduced the backend baseline from 495 to 420
diagnostics. After unrelated work reached `main`, the baseline collected from
commit `cb9748515` was 431 diagnostics.

The current backlog is grouped by root cause rather than individual file:

| Category | Count | Disposition |
| --- | ---: | --- |
| Test doubles and test dynamic data | 125 | Next bulk cleanup category |
| External Channel contracts | 110 | Requires separate contract review |
| API and Result-union narrowing | 103 | Preserve current policy; defer |
| Exhaustive unions and other contracts | 48 | Review by contract family |
| Production container narrowing | 19 | Validate by boundary family |
| Migration and third-party extensions | 13 | Do not edit executed migrations |
| TypedDict dynamic-key access | 10 | Mechanical read-boundary cleanup |
| Read-only protocol variance | 2 | Mechanical read-boundary cleanup |
| Callable naming contract | 1 | Requires explicit callable policy |

## Phase 7: Structural Read and Container Narrowing

The seventh documented phase groups structurally equivalent read-boundary fixes
instead of delivering isolated diagnostics.

This phase:

- Declares tool-call identity fields as read-only protocol properties so frozen
  admitted-call models satisfy the consumer contract.
- Accepts OpenAI response options through a read-only mapping in typed value
  readers while preserving the validated `OpenAIResponsesOptions` producer.
- Names the existing string-header validation as a TypeGuard without changing its
  accepted values or error behavior.
- Uses shared test TypeGuards before reading nested JSON dictionaries and mutating
  dynamically loaded lists.

### Phase 7 Result

The phase reduces the current-main baseline from 431 to 389 diagnostics:

- Structural read-only protocol diagnostics: 2 to 0
- OpenAI option dynamic-key diagnostics: 10 to 0
- Selected test container diagnostics: 29 to 0
- Existing credential-header container diagnostic: 1 to 0
- Pyright: 0 errors
- Targeted tests: 191 passed
- Backend tests: 3,942 passed

The next bulk category is test-double contract completion. Result unions,
External Channel contracts, generated code, and executed migrations remain outside
this mechanical phase.

## Phase 8: Runtime File Capability Protocols

The eighth phase replaces two over-broad Runtime Runner dependencies with the
specific file-operation capabilities their consumers invoke.

This phase:

- Defines the Skill scanner's list/read contract independently from unrelated
  Runtime process, write, edit, and patch operations.
- Separates managed Skill projection loading, file resolution, and action
  projection lookup into consumer-specific protocols.
- Defines the Workspace browser's list, preview, stat, create, delete, and move
  capability surface without requiring the complete Runner client.
- Makes Skill and Workspace test doubles expose exact keyword-compatible methods
  and correctly typed async session managers.
- Removes obsolete test suppressions without adding casts or new ignores.

### Phase 8 Result

The phase reduces the stacked baseline from 389 to 349 diagnostics:

- Skill Toolkit and projection test-double diagnostics: 22 to 0
- Workspace file-operation test-double diagnostics: 18 to 0
- Pyright: 0 errors
- Targeted tests: 35 passed
- Backend tests: 3,942 passed

VFS repository test doubles remain the next isolated test-contract batch.
Agent-decommission doubles remain separate because they cross the External Channel
lifecycle boundary.
