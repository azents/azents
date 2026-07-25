---
title: "Runtime File Transfer phase 3: Storage and transfer state"
created: 2026-07-25
tags: [runtime, files, transfer, s3, redis, backend, testenv]
---

# Runtime File Transfer phase 3: Storage and transfer state

## Phase Execution Plan

- Phase: `3 — Storage and transfer state`
- Branch/base: `feature/runtime-file-transfer-03-storage-state` → `feature/runtime-file-transfer-02-implementation-plan`
- PR boundary: Add bounded S3-compatible object operations, the complete transfer domain and state-store contract, conforming in-memory and Redis adapters, and Runtime Control-owned Transfer State composition. Preserve the existing Redis-backed Runtime Coordination path.
- Inputs: Confirmed `transfer-260725/REQ`; accepted `transfer-260725/ADR` including D10; corrected `transfer-260725/DESIGN`; `docs/azents/plans/runtime-file-transfer-implementation-plan.md`; current Runtime Control and file-storage specs; completed implementer discovery and independent plan review.
- Deliverables: Bounded object metadata/read/copy/multipart/abort/cleanup primitives; frozen transfer state values; atomic admission and fenced transition contract; memory/Redis parity; transfer-state backend composition; focused real RustFS evidence; no body-bearing state API.
- Non-goals: Runner-facing or internal coordinator protobuf/gRPC; Runner filesystem behavior; Runner Control transfer intent; feature consumer migration; provider command/environment forwarding; Helm rollout; lifecycle policy deployment; living-spec promotion; legacy compatibility; changing existing Runtime Coordination semantics or selecting memory for it.
- Interfaces: The contracts below are fixed before implementation. Implementation-specific helper names and private serialization may vary only when the observable contract and tests remain unchanged.

### Interface contract: bounded S3 operations

The shared S3 layer keeps all existing eager APIs for current bounded callers and adds transfer-safe operations. New operations must satisfy these rules:

- `head/stat` returns a frozen metadata value or a typed not-found result. Metadata includes content length, content type, ETag/backend checksum fields when present, user metadata, and last-modified evidence. It does not download the body.
- bounded object iteration is acquired through an async context manager that yields an async iterator of `bytes` chunks with an explicit configured maximum chunk size. Context exit owns response-body closure after completion, early consumer exit, cancellation, and exceptions; callers cannot receive an unowned plain iterator whose retained generator may leave the body open.
- immutable copy accepts explicit source and destination identities plus an allowlisted transfer metadata value, refuses silent destination reuse for an attempt object, and returns verified destination metadata. Copy and multipart-copy creation replace rather than inherit arbitrary source user metadata; only transfer-owned SHA-256 metadata and explicitly allowed content metadata may reach the attempt object.
- normal copy uses server-side copy when within the backend's supported limit. Conditional multipart copy uses bounded `upload_part_copy` work when the source exceeds that limit.
- multipart upload uses an opaque frozen upload handle containing only trusted-process identifiers. The contract supports create, ordered part upload, complete, and idempotent abort.
- multipart complete requires a non-empty ordered part manifest, exact expected size, required SHA-256 metadata, and final HEAD verification. Accepted zero-byte files use a direct immutable empty-object create-and-verify path with the standard SHA-256 of empty content rather than an invalid empty multipart completion.
- final verification always compares exact expected size and persisted transfer-owned SHA-256 metadata. It additionally validates a backend-native checksum when the backend returns one in a comparable form. S3-native copy may rely on an already trusted source SHA-256 plus destination HEAD metadata; tests independently read the destination through the bounded interface and hash its actual bytes.
- failed, cancelled, incomplete, oversized, or unverifiable multipart work is aborted and is never returned as a verified object. Failed, cancelled, or ambiguously completed single-copy work likewise never returns a verified object, attempts destination cleanup, and surfaces cleanup failure for transfer-state retry evidence.
- cleanup iteration is paginated and bounded. Transfer code must not materialize an unbounded prefix listing before deletion. Partial `DeleteObjects` success is reported per object so failed keys remain retryable instead of being counted as deleted.
- no transfer-safe operation calls `download_bytes()` or performs one unbounded body `read()`.

The initial public types are expected to include frozen equivalents of:

- object identity and object metadata;
- verified object metadata;
- multipart upload handle;
- completed part evidence; and
- bounded key/list page evidence.

These are library values only. They do not contain credentials or presigned URLs.

### Interface contract: transfer domain

Add a dedicated Runtime transfer package under `azents.runtime.transfer`. Domain values are frozen and contain no file bytes, provider credentials, public URLs, bearer headers, or public product identifiers.

The transfer record includes at least:

- `transfer_id` and immutable `attempt_id`;
- direction;
- Runtime ID, desired generation, and accepted Runner generation when known;
- owner operation and optional Session correlation;
- authorized Runtime path and overwrite policy;
- expected size and optional trusted expected SHA-256;
- actual size and authoritative SHA-256 when verified;
- phase, terminal outcome, cleanup status, and bounded error classification;
- revision and one-stream claim evidence;
- admission lease identity and expiry;
- object handle owned by the transfer layer;
- consumer claim and acknowledgement evidence;
- created/updated/deadline timestamps;
- authoritative source expiry when present;
- absolute logical content expiry equal to the earlier of one hour after attempt creation and authoritative source expiry; and
- terminal metadata expiry no later than one hour after settlement.

Closed enums cover direction, phase, terminal outcome, cleanup status, and typed failure classification. The phase path begins at `preparing` only after admission succeeds and may reach `ready`, `streaming`, `verifying`, `available`, `consuming`, `consumed`, `committed`, and terminal settlement according to direction. Cleanup status remains independent from terminal success or failure.

### Interface contract: RuntimeTransferStateStore

`RuntimeTransferStateStore` is a dedicated Protocol. Runtime Control is its only service owner. Phase 3 implements the contract and composition but does not expose it over the network; Phase 4 adds the authenticated coordinator and Runner transfer services.

The Protocol exposes domain operations equivalent to:

- atomically evaluate admission and create one lease-backed metadata-only `preparing` attempt;
- get a current non-expired attempt;
- transition preparation to `ready` with verified object metadata;
- claim exactly one data stream for the expected attempt, direction, generation, phase, and revision;
- coalesce bounded progress/heartbeat evidence;
- request cancellation;
- enter verification and publish verified `available` state;
- record Runtime destination `committed` state;
- claim, acknowledge, or abandon one trusted consumer lease;
- settle terminal outcome idempotently;
- record cleanup pending, complete, or retryable failure independently from terminal outcome;
- release admission idempotently;
- list expired, stale-lease, or cleanup-pending records in bounded pages; and
- purge expired content-free terminal metadata.

Required atomic/fencing semantics:

- admission checks all configured per-Runtime and deployment budgets before persisting the lease and attempt metadata;
- concurrent and duplicate admission at a capacity boundary cannot oversubscribe counters or reserve the same logical attempt twice;
- rejection creates neither lease nor attempt metadata and invokes no downstream preparation callback;
- every mutation compares the expected attempt ID, phase, revision, Runtime identity, and applicable generation;
- exactly one stream claim and exactly one active consumer claim can succeed;
- terminal settlement is idempotent and cannot be replaced by a late success, cleanup, or older attempt;
- old-attempt cleanup cannot delete or settle a newer attempt;
- ready/streaming/consumer transitions require a live admission lease and unexpired logical content;
- expired admission and consumer leases are reclaimed atomically, release their corresponding capacity or claim, and cannot authorize a stale owner mutation;
- heartbeats, progress, retries, and consumer activity never extend absolute content expiry;
- physical object existence never reconstructs or revives missing/expired state;
- progress persistence is coalesced and never written once per body chunk; and
- no method accepts or returns file-body chunks.

Typed admission input includes declared size, applicable product/provider maximum, direction, Runtime identity/generation, deadline, source expiry, and requested resource class. Phase 3 defines reversible configuration values for per-Runtime active attempts, admitted bytes, deployment attempts/bytes, lease duration, terminal TTL, and bounded list page size. Concrete production defaults remain Phase 9 deployment configuration, but tests use explicit values.

### Interface contract: in-memory adapter

`InMemoryRuntimeTransferStateStore`:

- uses one `asyncio.Lock` for atomic contract operations;
- accepts an injected timezone-aware clock;
- actively expires records, leases, consumer claims, and terminal metadata on access/list operations;
- applies the same admission counters, revision fencing, transition validation, and pagination semantics as Redis;
- fails closed after process restart and never infers success from object presence; and
- is tested without Redis at the isolated store-contract layer.

### Interface contract: Redis adapter

`RedisRuntimeTransferStateStore`:

- uses a transfer-specific key namespace separate from Runtime Coordination;
- uses Lua/CAS/transactions for admission, counters, revision-fenced transitions, claims, cancellation, settlement, and release;
- preserves absolute expiry instead of refreshing it from heartbeats or transitions;
- uses lease-backed counters that can be reclaimed after owner loss;
- maintains bounded serialized records and indexes with TTL; and
- passes the exact parameterized contract suite used by the memory adapter.

Redis adapter serialization is private. The public Protocol and domain values do not expose Redis keys, scripts, streams, or serialization details.

### Interface contract: Runtime Control composition

Phase 3 adds transfer-state composition only:

- existing `RuntimeCoordinationStore` construction remains Redis-backed and behaviorally unchanged in API/Worker and Runtime Control;
- Runtime Control selects only `RuntimeTransferStateStore` as `memory` or `redis`;
- `redis` Transfer State may reuse the Runtime Control Redis client lifecycle while keeping a separate namespace and Protocol;
- `memory` Transfer State constructs one process-local owner and is never injected into API Server or Worker;
- phase 3 may add backend selection settings/factory tests, but no internal coordinator endpoint or credential configuration; those belong to phases 4 and 9; and
- regression tests prove existing Runtime Coordination routing/connection behavior is unchanged.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Bounded S3 primitives | `/root/runtime-transfer-implementer` | `python/libs/az-common/src/azcommon/infra/s3/`; focused unit tests in the same project; focused RustFS integration support/tests under `testenv/azents/e2e/` | Approved object contract | Metadata, bounded iterator, immutable copy, conditional multipart copy, multipart lifecycle, verified completion, bounded cleanup | az-common Ruff/format/Pyright/Pytest; focused real RustFS testenv checks |
| Transfer domain and state stores | `/root/runtime-transfer-implementer` | new `python/apps/azents/src/azents/runtime/transfer/` modules and tests | Approved transfer/store contracts | Frozen domain values, Protocol, memory adapter, Redis adapter, shared contract suite | targeted backend tests against memory and real Redis; injected-clock and concurrency/fencing cases; backend Ruff/format/Pyright |
| Transfer-state composition | `/root/runtime-transfer-implementer` | transfer-specific settings/factory modules and focused `python/apps/azents/src/azents/runtime/control_server*.py` tests only as required; existing coordination implementation is read-only except regression tests | State adapters complete | Runtime Control-only memory/Redis Transfer State composition with unchanged Redis Coordination | composition/config tests; existing coordination contract and control-server regression tests |
| Phase integration and scope verification | `/root` | phase plan, integration inspection, accepted review fixes, git/PR metadata | All implementation workstreams | Verified cohesive Phase 3 diff with no later-phase code | full phase command matrix, diff/non-goal review, independent reviewer handoff |

- Integration order: (1) define S3 public values and bounded operations with unit tests; (2) prove real RustFS behavior; (3) define transfer domain and Protocol; (4) implement memory adapter and contract suite; (5) implement Redis adapter against the same suite; (6) add transfer-state composition while preserving Redis Coordination; (7) run complete validation and scope comparison.
- Independent review: `/root/runtime-transfer-reviewer` reviews the cumulative Phase 3 diff after primary verification. Criteria: no whole-body buffering in new S3 APIs; response close and multipart abort on cancellation/failure; exact size/SHA verification; bounded pagination; no bytes/secrets in state; atomic admission; absolute source-expiry ceiling; memory/Redis parity; stale attempt/generation/revision fencing; idempotent release/settlement/cleanup; existing Runtime Coordination unchanged; no Phase 4 protocol/auth code.
- Final validation:
  - `cd python/libs/az-common && uv sync && uv run ruff check . && uv run ruff format --check . && uv run pyright . && uv run pytest -vv`
  - `cd python/apps/azents && uv sync && uv run ruff check . && uv run ruff format --check . && uv run pyright . && uv run pytest -vv src/azents/runtime/transfer src/azents/runtime/coordination/store_contract_test.py src/azents/runtime/control_server_test.py`
  - `cd testenv/azents/e2e && uv sync && uv run ruff check . && uv run ruff format --check . && uv run pyright . && uv run pytest -vv src/tests/test_runtime_transfer_storage.py`
  - `git diff --check`
  - pre-commit on every changed file before commit.
- Scope-drift check: Compare the final diff with this plan and the Phase 3 section of the multi-phase plan. Reject Runner/coordinator protobuf or gRPC, feature consumers, provider/Helm rollout, product metadata changes, living-spec promotion, generic gRPC limit increases, presigned Runner access, direct Runner S3 authority, body-bearing Redis/Transfer State fields, replacement of Redis Runtime Coordination, or unrelated refactors. Move such work to its planned later phase before commit.

## Test cases required before independent review

### S3 unit and RustFS integration

- missing HEAD returns the typed not-found outcome while unexpected S3 errors propagate;
- bounded iteration returns exact ordered bytes across multiple chunks and closes the body on completion, early exit, cancellation, and read failure;
- no new transfer API calls `download_bytes()` or an unbounded body `read()`;
- immutable copy strips arbitrary source user metadata, preserves only the allowlisted transfer/content metadata, verifies exact size/SHA evidence, and does not overwrite an existing attempt destination;
- conditional multipart copy produces ordered parts and exact destination metadata, and cancellation or ambiguous completion aborts or deletes the attempt destination without returning verified evidence;
- zero-byte creation produces a verified immutable object without attempting empty multipart completion;
- multipart create/upload/complete returns verified metadata only after exact size and SHA-256 checks;
- failed part, invalid part order, completion failure, size mismatch, checksum mismatch, cancellation, and explicit abort leave no verified object and call abort idempotently;
- paginated prefix iteration/deletion never collects the full prefix in memory and preserves per-key retry evidence after a partial bulk-delete failure;
- real RustFS validates copy, multipart upload, multipart abort, bounded read, metadata HEAD, zero-byte handling, and cleanup behavior. It hashes bytes read from each completed object and compares the result with the expected SHA-256 rather than validating metadata persistence alone.

### Shared transfer-store contract

Run each applicable case against memory and Redis:

- admission success creates one metadata-only preparing attempt and reserves counters;
- admission rejection creates no record/lease and invokes no downstream callback;
- per-Runtime and deployment attempt/byte budgets reject deterministically;
- concurrent admissions at the final capacity slot allow exactly one winner without oversubscription;
- duplicate admission is idempotent or rejected without double-reserving attempts or bytes;
- expired admission leases reclaim counters, and the expired owner cannot mutate the attempt;
- expired consumer leases release the claim, and the expired consumer cannot acknowledge or abandon it;
- source expiry earlier than one hour becomes the absolute content expiry;
- absent or later source expiry uses exactly the one-hour absolute content cap;
- an already-expired source is rejected before admission state is created;
- active-attempt expiry releases admission capacity while retaining bounded terminal and cleanup evidence;
- heartbeat/progress/consumer activity does not extend absolute expiry;
- ready cannot succeed without a live lease, correct attempt, phase, and revision;
- exactly one stream claim succeeds under concurrency;
- stale desired generation, accepted Runner generation, attempt, phase, or revision cannot mutate current state;
- cancellation races with claim/verification/settlement and preserves one terminal authority;
- duplicate terminal settlement and admission release are idempotent;
- late success cannot replace failed/cancelled/expired/superseded outcome;
- available consumer claim is exclusive, lease-backed, and fenced;
- acknowledge/abandon preserves terminal outcome and cleanup state separation;
- cleanup failure records retryable evidence without reversing success;
- old-attempt cleanup cannot affect a newer attempt;
- expired or missing state cannot be revived from object identity;
- bounded expired/cleanup listing paginates deterministically;
- content-free terminal metadata expires within its configured ceiling;
- serialized Redis record contains no file bytes, credentials, presigned URLs, provider URLs, or public product URI.

### Composition and regression

- default Runtime Control transfer-state composition remains Redis-backed;
- explicit memory Transfer State creates one process-local store only inside Runtime Control;
- memory Transfer State coexists with Redis Runtime Coordination;
- API/Worker and Runtime Control existing coordination dependencies remain Redis-backed;
- existing Runtime Coordination contract tests and Runtime Control settings/transport tests remain green; and
- no Phase 3 code exposes an internal coordinator or Runner transfer RPC.

## Handoff contract

The implementation owner receives and must follow:

- `docs/azents/requirements/transfer-260725-runtime-file-transfer.md`
- `docs/azents/adr/transfer-260725-runtime-file-transfer.md`
- `docs/azents/design/transfer-260725-runtime-file-transfer.md`
- `docs/azents/plans/runtime-file-transfer-implementation-plan.md`
- this phase execution plan
- root and Python project instructions plus applicable convention bodies

Any missing detail that changes a public S3/state interface, process ownership, security boundary, retention rule, or phase scope must be reported to `/root` before implementation continues. Private helper structure, serialization shape, and test organization may be chosen autonomously within the fixed contracts.
