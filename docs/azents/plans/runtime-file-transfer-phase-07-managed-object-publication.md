---
title: "Runtime File Transfer phase 7: Managed-object publication"
created: 2026-07-26
tags: [runtime, files, transfer, exchange, artifact, engine]
---

# Runtime File Transfer phase 7: Managed-object publication

## Phase Execution Plan

- Phase: `7 — Managed-object publication`
- Branch/base: `feature/runtime-file-transfer-07-managed-publication` → `feature/runtime-file-transfer-06-server-to-runtime-consumers`
- PR boundary: Replace adopted Runtime-to-server complete-file publication with a verified Runtime upload object and trusted object-native Exchange or Artifact publication. `present_file` reports success only after Exchange metadata commits.
- Inputs: Confirmed `transfer-260725/REQ`; accepted `transfer-260725/ADR`; approved `transfer-260725/DESIGN`; `docs/azents/plans/runtime-file-transfer-implementation-plan.md`; completed Phase 3 storage/state, Phase 4 coordinator protocol, Phase 5 Runner upload contract, and Phase 6 consumer/source-preparation contracts; Phase 7 implementer and reviewer discovery baselines.
- Deliverables: Unknown-digest Runtime upload readiness; trusted Runtime-to-server consumer orchestration; renewable consumer claims and recovery-safe acknowledgement/settlement; product-safe native S3 copy; Exchange and Artifact verified-object publication; bounded text/image previews; `present_file` migration; exact compensation/error semantics; focused large-file and retry evidence.
- Non-goals: External Channel outbound delivery; Exchange/Artifact publication from arbitrary unverified objects; new public file identity or retention policy; deployment, provider environment, Helm, credential, endpoint, or protocol rollout wiring; ordinary bounded `FileStorage.get()`, `file.read`, `file.write`, edit, patch, or text-tool behavior; Runner S3 access; presigned URLs; a gRPC message-limit increase; an RDB transfer entity or migration; whole-body compatibility fallback; protected existing-destination replacement; living-spec promotion.
- Interfaces: The contracts below are fixed before implementation. Phase 7 may narrowly extend only the trusted coordinator/state/client contract for upload unknown-digest readiness and consumer-lease renewal/recovery. It does not alter Runner-facing streaming frames or give Runner object-store authority.

### Interface contract: Runtime upload admission and readiness

`RuntimeToServerTransferService` is a backend-only companion to the Phase 6
Server-to-Runtime service. It accepts:

- a trusted Runtime target, current desired Runner generation, and absolute Runtime source path;
- the initiating Agent, Session, Run, operation correlation, and stable logical transfer identity;
- exact stat size and applicable product/provider maximum sizes;
- authoritative feature/source expiry when present;
- a consumer category and stable publication correlation; and
- an absolute operation deadline.

The upload admission accepts an expected size and an **optional** expected SHA-256.
For `present_file`, no full-file pre-read, dummy digest, ordinary `file.read`, or
`FileStorage.get()` is permitted to obtain a digest. The Runner snapshots the admitted
path and streams through the existing dedicated upload RPC. Runtime Control computes
actual size and SHA-256 while receiving bounded chunks, verifies the immutable transfer
object, and only then records the object as available with the actual manifest.

The trusted coordinator/state contract must distinguish an upload with unknown expected
SHA-256 from an invalid manifest. It preserves admission, attempt, desired generation,
accepted Runner generation, deadline, stream claim, and revision fencing. The actual
manifest is immutable once verified. A mismatched stat size, source mutation/snapshot
failure, size-limit failure, cancellation, deadline, disconnect, or generation
replacement settles the exact attempt without making an object available.

No Runner-facing data-RPC field, Runner credential, storage key, bucket, URL, body, or
product identity is added. The optional expected digest and actual manifest remain
bounded trusted coordinator metadata.

### Interface contract: verified-object consumer orchestration

The service owns one upload attempt through:

1. feature authority, Runtime target/path, stat size, limit, deadline, and consumer
   preflight;
2. metadata-only admission before upload intent dispatch;
3. metadata-only upload dispatch and wait for exact verified-object availability;
4. consumer claim, verified-object resolution, and lease maintenance;
5. feature-owned product publication;
6. consumer acknowledgement only after product metadata commits; and
7. authoritative successful transfer settlement and cleanup observation.

Dispatch acknowledgement alone is not feature success. A verified object alone is not
product success. `present_file` succeeds only after Exchange metadata commits and the
consumer acknowledgement/settlement path has reached its authoritative successful state,
or a status read proves that exact successful settlement already occurred.

The service uses only the typed `GrpcRuntimeTransferCoordinatorClient`; feature services
never access Transfer State, object-store keys, or Runtime Coordination directly. A
trusted-process-only verified-object lease exposes an opaque handle plus exact verified
size, SHA-256, media type, logical expiry, current revision, and consumer claim ID. It
never reaches Runner, model-visible output, public API values, Redis, or logs.

### Interface contract: renewable claim, stable identity, and recovery

Consumer claims are revision-fenced and renewable. The trusted coordinator/client gains a
closed operation equivalent to `RenewConsumerLease` for the exact transfer, attempt,
claim, and current revision. Renewal:

- is valid only while the same claim is live, the object is available/consuming, the
  deadline and logical expiry are live, and the expected revision matches;
- returns current bounded status and revision;
- cannot revive an expired, abandoned, consumed, terminal, superseded, or replacement
  attempt; and
- runs under a bounded schedule before the existing claim lease expires, stopping before
  acknowledgement, abandonment, cancellation, or terminal state.

Each publication derives one stable, trusted product identity from the logical transfer
and consumer category before object publication. The identity is reused after a copy,
commit, acknowledgement, or settlement transport uncertainty. It is not a new public
identity policy and is not stored as public transfer metadata. Existing Exchange and
Artifact caller-selected IDs and final keys are the persistence anchor; no transfer RDB
entity or migration is introduced.

Publication recovery rules:

- before DB commit, a feature failure abandons the exact live claim after compensating
  only its exact uncommitted product object;
- after DB commit but before acknowledgement, a retry resolves the stable product ID,
  verifies its authority/source manifest relationship, and retries acknowledgement
  rather than creating another product;
- acknowledgement is retried or status-confirmed for the exact claim; a `CONSUMED`
  observation is equivalent to an accepted acknowledgement for that claim;
- after acknowledgement, settlement is retried/status-confirmed until the exact
  successful terminal result is observed; and
- cleanup transport failure never reverses a committed Exchange or Artifact product.

The service retains the feature's original failure if best-effort abandonment,
acknowledgement, settlement, or cleanup observation has an ordinary transport failure.
Cancellation propagates `CancelledError` after exact cancellation/abandonment is
requested; it never reports product success before the product commit boundary.

### Interface contract: product-safe S3 publication

Add a separate bounded S3 product-publication primitive. It is not
`copy_immutable()`, which remains transfer-snapshot-specific, and it must not use the
unrestricted `copy()`/`delete()` pair for managed publication.

The primitive receives trusted source and destination descriptors and:

- fences the source with the verified object handle, exact size, SHA-256, and stable
  source version/ETag evidence when the backend supplies it;
- copies natively from the verified transfer object to one preallocated product key
  without application body download/re-upload;
- preserves or applies only product-owned content type and bounded product metadata;
- fails closed if an existing destination is not the same stable publication identity
  with the exact expected final manifest;
- treats an existing destination with the same stable identity and verified manifest as
  idempotent recovery, not an overwrite;
- verifies final size, SHA-256/integrity evidence, and ownership marker before DB
  commit; and
- conditionally deletes only the exact uncommitted destination whose stable identity
  and expected manifest still match.

An unexpected final key, source version/manifest mismatch, metadata mismatch, uncertain
copy result, or conditional-compensation mismatch is a concrete publication failure.
It never deletes the verified transfer source or another product's key. Storage details
remain trusted implementation data.

### Interface contract: Exchange and Artifact object-source publication

Exchange and Artifact gain internal `create_from_verified_object`-equivalent paths. The
existing body-based APIs remain for unchanged bounded callers; Phase 7 adopts the
object-source path only for Runtime transfer consumers.

For each product, the path:

1. validates authority and product-specific limits, derives stable product ID/final key,
   and checks whether that stable ID already committed a matching publication;
2. closes the DB session before object I/O;
3. invokes product-safe native S3 copy;
4. performs only required bounded preview/transformation work;
5. opens a fresh transaction, locks/revalidates authority, ownership, source validity,
   and stable product identity;
6. commits product metadata exactly once; and
7. conditionally compensates the uncommitted final object on every pre-commit failure.

Exchange text preview incrementally decodes the complete object with strict UTF-8,
rejects unsupported controls anywhere in the stream, and retains no more than the
existing configured preview prefix. Exchange image preview streams into a configured
spooled/disk-backed seekable temporary input, cleans it on every exit, and retains only
bounded thumbnail output. Other unchanged media types require no object body read after
native copy. Artifact performs no new preview read unless its existing product contract
requires one.

### Interface contract: `present_file`

`present_file` keeps its existing path allowlist, per-path stat, Agent/Session authority,
filename/media-type handling, partial-success attachment behavior, and controlled
inaccessible-file result contract.

For every accepted path it:

1. performs bounded Runtime stat without reading the complete body;
2. invokes the backend-only Runtime-to-server capability for one upload/publication
   operation;
3. waits for exact Exchange commit and transfer settlement; and
4. reports only committed Exchange attachments as successes.

The Runtime instruction capability receives trusted Runtime ID/generation, typed
coordinator client/service, and bounded settings only. It contains no bytes, object
keys, bucket, provider URL, credential, or Runner secret. `present_file` does not call
`FileStorage.get()` for adopted complete-file publication and does not add an ordinary
`file.read` fallback.

### Interface contract: failure, expiry, and observability

- Initial authority/limit rejection occurs before verified-object resolution, source
  copy, preview, or product key allocation that creates an object.
- A live claim is renewed through copy, preview, and DB commit; lease loss before
  commit prevents acknowledgement and produces a concrete retryable failure.
- Logical transfer expiry, consumer expiry, cancellation, generation replacement,
  source/manifest mismatch, copy failure, preview failure, DB failure, acknowledgement
  failure, or settlement failure cannot become product success.
- Product commit is irreversible by transfer cleanup; post-commit acknowledgement or
  cleanup uncertainty is reconciled via stable identity and exact transfer status.
- Logs expose only bounded transfer/attempt/product correlation IDs, category, phase,
  size, checksum outcome, and failure class. They exclude bytes, product keys, object
  handles, buckets, URLs, credentials, and tokens.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Upload unknown-digest readiness and renewable consumer claim | `/root/runtime-transfer-implementer` | trusted coordinator proto/client; `runtime/transfer/{data,store,memory,redis,coordinator,object_store}.py`; control upload server and tests | Phases 3-6 transfer state/protocol | Optional upload expected digest, actual verified manifest readiness, renewable consumer lease, exact acknowledgement/settlement recovery | Generated client drift; memory/Redis contract parity; upload unknown-digest/zero-byte/generation/cancel tests |
| Runtime-to-server orchestration | `/root/runtime-transfer-implementer` | focused new modules under `runtime/transfer/`; tests | Upload readiness, consumer contract | Admission/dispatch/available/claim/renew/get/ack/settle service with stable publication correlation | Focused terminal, lease, deadline, cancellation, retry, and transport uncertainty tests |
| Product-safe native S3 copy | `/root/runtime-transfer-implementer` | `python/libs/az-common/src/azcommon/infra/s3/`; tests | Verified object manifest and product final-key contract | Source-fenced, destination-safe, verified copy and conditional compensation | az-common Ruff/format/Pyright/pytest; copy collision/manifest/compensation tests |
| Exchange and Artifact verified-object publication | `/root/runtime-transfer-implementer` | `services/exchange_file/`, `services/artifact.py`, repositories only if focused helpers are required; tests | Publication copy and consumer lease | Stable preallocation/idempotent resume, DB revalidation/commit, compensation, bounded preview | Service/transaction/preview/authority/retry tests |
| `present_file` capability and migration | `/root/runtime-transfer-implementer` | `engine/tools/present_file.py`, `runtime_instruction_context.py`, `builtin.py`, composition seam only; tests | Runtime-to-server and Exchange publication | No complete Runtime body relay; commit-only tool success | Tool/lifecycle tests; no-`FileStorage.get` spies; >4 MiB evidence |
| Independent review and final verification | `/root/runtime-transfer-reviewer`, then `/root` | Read-only cumulative Phase 7 diff; root owns final PR verification/shipping | Implementation owner validation complete | Findings/recheck and root scope validation | Authorization, lease, retry, copy, preview, compensation, no-leak, and non-goal audit |

- Integration order: (1) add upload unknown-digest readiness and renewable consumer lease contracts with generated clients; (2) add product-safe S3 copy and test doubles; (3) implement Runtime-to-server orchestration and exact recovery; (4) add Exchange/Artifact object-source publication and bounded previews; (5) inject upload capability and migrate `present_file`; (6) run full focused validation; (7) implementation owner requests reviewer, fixes all accepted Critical/Warning findings, reruns validation, and requests same-reviewer recheck.
- Independent review: The implementation owner requests review directly from `/root/runtime-transfer-reviewer`. Review criteria: no upload pre-hash/full body relay; admission before transfer/object work; exact upload integrity; claim renewal/fencing; stable publication identity; ack after DB commit only; idempotent recovery around ack/settle uncertainty; source/destination native-copy safety; bounded previews/spool cleanup; exact compensation; no product-success reversal; no bytes/secrets/keys in untrusted paths; no Phase 8/9 behavior.
- Final validation:
  - `cd python/libs/az-common && uv run ruff check . && uv run ruff format --check . && uv run pyright . && uv run pytest -vv` when shared S3 code changes.
  - `cd python/libs/azents-runtime-control && uv run python scripts/generate_proto.py && git diff --exit-code -- src/azents_runtime_control/proto && uv run ruff check . && uv run ruff format --check . && uv run pyright . && uv run pytest -vv` when trusted coordinator protocol changes.
  - `cd python/apps/azents && uv run ruff check . && uv run ruff format --check . && uv run pyright .`
  - `cd python/apps/azents && uv run pytest -vv src/azents/runtime/transfer src/azents/engine/tools/present_file_test.py src/azents/engine/io/file_resource_lifecycle_verification_test.py src/azents/services/exchange_file/service_test.py src/azents/services/artifact_test.py`
  - Focused real S3/RustFS publication evidence when the fixture is available; Phase 10 remains the full E2E gate.
  - `git diff --check feature/runtime-file-transfer-06-server-to-runtime-consumers..HEAD`
  - pre-commit on every changed file before commit.
- Scope-drift check: Reject External Channel outbound delivery, provider-native upload work, `import_file` rework, deployment/provider/Helm wiring, new public identity or retention policy, Runner S3 access, presigned URLs, Runner data-RPC frame changes, gRPC limit increases, body-bearing coordinator/Redis/control values, ordinary bounded file-operation rewrites, full-body compatibility fallback, protected overwrite rollout, living-spec promotion, or unrelated refactors.

## Required evidence before independent review

- A Runtime file with no precomputed SHA-256 uploads through the dedicated transfer path,
  receives an actual verified SHA-256, and is unavailable on size, snapshot, integrity,
  cancellation, deadline, or generation failure.
- `present_file` publishes Exchange and Artifact targets larger than 4 MiB without
  `FileStorage.get()`, ordinary `file.read`, `download_bytes()`, or a complete
  application body relay.
- The final product copy is native, source-manifest-fenced, destination fail-closed or
  exact-idempotent, and conditionally compensates only its exact uncommitted key.
- Consumer publication renews a claim longer than the old 60-second lease, rejects
  stale/lost claims before commit, acknowledges only after DB commit, and resumes a
  committed stable product after acknowledgement or settlement transport uncertainty
  without a duplicate row or object.
- Exchange text preview validates split UTF-8 and invalid/control characters anywhere
  in the stream while retaining only the configured prefix; image spool input and all
  temporary files are released on success, failure, and cancellation.
- Authority denial occurs before verified-object resolution/copy; locked authority
  revalidation and DB failure compensate the exact uncommitted object without deleting
  the verified transfer source or committed product.
- No Runner, model, public API, coordinator, Redis, control log, or result contains file
  bytes, product/object keys, bucket, URL, credential, or presigned access.
