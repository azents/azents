---
title: "Runtime File Transfer phase 4: Control transfer protocol"
created: 2026-07-25
tags: [runtime, files, transfer, grpc, security, backend]
---

# Runtime File Transfer phase 4: Control transfer protocol

## Phase Execution Plan

- Phase: `4 — Control transfer protocol`
- Branch/base: `feature/runtime-file-transfer-04-control-protocol` → `feature/runtime-file-transfer-03-storage-state`
- PR boundary: Add the versioned Runner transfer and trusted internal coordinator protocols, authenticated Runtime Control services, bounded Runner Control transfer intent correlation, and Runtime Control-owned S3/state composition. Do not implement production Runner filesystem behavior or migrate feature consumers.
- Inputs: Confirmed `transfer-260725/REQ`; accepted `transfer-260725/ADR` including D10; `transfer-260725/DESIGN`; `docs/azents/plans/runtime-file-transfer-implementation-plan.md`; completed Phase 3 state and S3 primitives; current Agent Runtime Control living spec; Phase 4 repository discovery.
- Deliverables: Two protobuf services and generated artifacts; shared coordinator client values; a distinct trusted-service credential authority; Runner transfer authentication and stream fencing; bounded download/upload service implementations; metadata-only coordinator service; metadata-only Runner Control intent/cancellation/result correlation; Runtime Control S3 and Transfer State lifespan wiring; real default-limit gRPC evidence above 4 MiB.
- Non-goals: Production Runner transfer channel/filesystem implementation; feature consumer migration; managed-object publication; provider delivery; Helm or deployment propagation; cleanup reconciler deployment; living-spec promotion; mixed-version compatibility; legacy inline-binary fallback; changing existing Redis Runtime Coordination semantics; raising any gRPC message limit.
- Interfaces: The public protobuf, credential, authorization, control-correlation, and byte-pipeline contracts below are fixed before implementation. Private helper names and test organization may vary only when the observable contract and phase boundary remain unchanged.

## Fixed protocol constants

- Runner protocol version: `2026-07-25`, strictly replacing `2026-07-20` at the coordinated cutover owned by Phase 9.
- Runner capability: `file.transfer.v1`.
- Runner transfer protobuf package: `azents.runtime_control.v1`.
- Internal coordinator audience: `azents-runtime-transfer-coordinator`.
- Trusted caller service identities: `azents-api` and `azents-worker`; tests may use an explicit test identity accepted only by injected policy.
- Trusted-service credential version/domain is distinct from Runner credentials and provider credentials.
- Trusted-service credential maximum lifetime: 60 seconds, with at most 5 seconds of configured clock skew for not-before validation.
- Maximum transfer chunk data: 256 KiB. Every sender rejects or splits larger data before protobuf serialization, and every receiver rejects an oversized frame before storage or checksum work.
- Multipart aggregation uses the backend-compatible minimum non-final part size, 5 MiB, with one in-flight part per upload in this phase. Chunk messages remain 256 KiB or smaller; no multipart part is one gRPC message.
- The implementation must not set `grpc.max_send_message_length`, `grpc.max_receive_message_length`, or equivalent channel/server options.

Protocol constants live in the shared `azents-runtime-control` library so Control, the synthetic Phase 4 Runner, and the production Phase 5 Runner use one definition. Phase 4 defines the exact registration acceptance matrix, but Phase 9 owns enabling strict production rejection during coordinated deployment.

## Interface contract: Runner transfer protobuf

Add `proto/azents/runtime_control/v1/runtime_runner_transfer.proto` and generate its Python service modules.

The service is direction-specific and Runner-initiated:

```protobuf
service RuntimeRunnerTransfer {
  rpc DownloadTransfer(DownloadTransferRequest)
      returns (stream DownloadTransferFrame);
  rpc UploadTransfer(stream UploadTransferFrame)
      returns (UploadTransferResult);
}
```

Shared identity contains exactly:

- `transfer_id`;
- `attempt_id`;
- `runtime_id`; and
- accepted `runner_generation`.

The bearer credential remains authoritative for Runtime ID and desired generation. Repeated identity fields are mismatch checks and diagnostic correlation, not caller-selected authority. No Runner transfer message contains a bucket, object key, object handle, S3 credential, URL, provider identity, public URI, Session/Agent authorization claim, or complete file body.

`DownloadTransfer` contract:

- request contains only the shared transfer identity;
- successful responses contain ordered `TransferChunk { offset, data }` frames followed by exactly one `DownloadTransferComplete { actual_size, sha256 }` frame;
- chunks are non-empty except that a zero-byte file sends no chunk and only the completion frame;
- offsets begin at zero and equal the next byte position;
- completion is sent only after the complete immutable object body has been read and verified against the admitted manifest;
- cancellation, deadline, read failure, mismatch, or missing object closes the RPC without a completion frame;
- Runtime destination commit is not inferred from stream completion and remains a bounded Runner Control result in Phase 5.

`UploadTransfer` contract:

- the first frame is exactly one `UploadTransferOpen` containing shared identity;
- later frames are ordered `TransferChunk` frames followed by exactly one `UploadTransferComplete` declaration containing Runner-observed size and SHA-256;
- chunk before open, repeated open, empty chunk, repeated completion, data after completion, missing completion, offset mismatch, size overflow, or trailing data is a protocol/integrity failure;
- Runtime Control independently counts and hashes received bytes and treats Runner completion values only as validation inputs;
- zero-byte upload contains open then completion and uses the Phase 3 verified empty-object path;
- success returns only authoritative actual size, SHA-256, and a bounded success classification; it returns no object identity or storage authority;
- error details are bounded and use gRPC status plus transfer failure classification rather than body-bearing diagnostics.

The generator input set becomes Provider Control, Runner Control, Runner Transfer, and Transfer Coordinator. Generated `*_pb2.py` and `*_pb2_grpc.py` files and the Pyright generated-file exclusions cover all four services.

## Interface contract: bounded Runner Control correlation

Extend `runtime_runner_control.proto` without adding bytes to the Control stream.

A top-level `RunnerTransferIntent` delivered in `RunnerControlMessage` contains:

- shared transfer identity and direction;
- initiating `operation_id` and nullable owner Session correlation already authorized by the trusted caller;
- authorized Runtime path and overwrite policy;
- expected size and optional expected SHA-256;
- absolute deadline;
- protocol version and capability; and
- a bounded request/correlation ID.

A top-level `RunnerTransferCancel` contains only transfer/attempt/operation correlation and cancellation classification. A top-level `RunnerTransferResult` returned in `RunnerMessage` contains only identity, operation correlation, bounded terminal classification, actual size/SHA-256 when applicable, and Runtime destination commit evidence for download. It contains no file bytes, local temporary path, object identity, credential, or unbounded error text.

Routing reuses the existing Redis-backed Runtime Coordination request/reply and operation metadata boundary only for bounded intent and status:

- coordinator dispatch appends one metadata-only transfer-intent request;
- the Runner gRPC bridge maps that request to `RunnerTransferIntent` rather than `RunnerOperationRequest.body_chunks`;
- no transfer body stream is created or read from Runtime Coordination;
- ordered cancellation maps to `RunnerTransferCancel` for the same operation;
- Runner transfer results are correlated promptly to the initiating operation and folded into its bounded terminal result;
- a known data-path failure must not wait for the generic operation timeout;
- ordinary bounded file/process/Git operations and their existing body-stream behavior remain unchanged in this phase.

Transfer intent admission and execution do not consume or block the data-stream semaphores. Runner-side scheduling isolation and filesystem publication are Phase 5, but Phase 4 tests prove Control heartbeat and ordinary bounded operations remain responsive while a separate transfer RPC is active.

## Interface contract: trusted coordinator protobuf

Add `proto/azents/runtime_control/v1/runtime_transfer_coordinator.proto`, generated artifacts, shared immutable request/result values, and `GrpcRuntimeTransferCoordinatorClient` in `python/libs/azents-runtime-control`.

The coordinator service exposes metadata-only RPCs equivalent to:

- `AdmitTransfer` — atomically admit a metadata-only preparing attempt and return bounded attempt state plus an opaque admitted object handle;
- `MarkTransferReady` — accept trusted verified object metadata and transition a download attempt to ready;
- `DispatchTransfer` — bind the current accepted Runner generation and append one bounded Runner Control intent;
- `CancelTransfer` — persist cancellation, correlate ordered Runner cancellation, and return bounded state;
- `GetVerifiedObject` — return an opaque unexpired verified-object handle and manifest only for an authorized upload consumer;
- `ClaimConsumer`, `AcknowledgeConsumer`, and `AbandonConsumer` — own the trusted consumer lease lifecycle;
- `SettleTransfer` — record one idempotent bounded terminal outcome;
- `RecordCleanup` — record cleanup pending, complete, or retryable failure independently from feature success; and
- `GetTransferStatus` — return bounded metadata/status for operation correlation and cleanup observation.

RPC naming may be adjusted only before generation if protobuf style or an existing symbol requires it; the operation set and authority boundaries may not be reduced or combined into a generic arbitrary-transition endpoint.

Coordinator messages may contain transfer and attempt identity, Runtime identity/generation, operation/Session/Agent correlation when applicable, direction, Runtime path, overwrite, manifests, deadlines, source expiry, resource class, revisions, lease/claim identifiers, terminal classifications, cleanup status, and opaque internal handles. They must not contain `bytes` fields, Base64 body fields, repeated chunks, provider URLs, bearer credentials, public download URLs, or Runner credentials.

Opaque object handles are attempt-scoped trusted-service values. They expose no bucket, endpoint, credential, or presigned authority and are never accepted from Runner-facing RPCs. Later feature phases may pass them only to trusted transfer/object helpers; Phase 4 does not add product identity or publication behavior.

Runtime Control remains the only `RuntimeTransferStateStore` owner. The client library never constructs or imports a Transfer State implementation.

## Interface contract: trusted-service credentials

Add a coordinator-specific short-lived signed credential authority rooted in `credential_encryption_key` with a new domain-separated key. It is not a static shared bearer token and is not wire-compatible with Runner or Provider credentials.

Each signed credential contains and validates:

- credential version and unique nonce;
- exact audience `azents-runtime-transfer-coordinator`;
- trusted service identity;
- exact coordinator RPC operation;
- issued-at, not-before, and expiry timestamps;
- Runtime ID;
- transfer ID and attempt ID when they exist for the operation;
- direction when applicable;
- initiating operation ID;
- nullable Session ID and Agent ID when applicable; and
- a signature over one canonical bounded encoding.

Issuance requirements:

- API/Worker callers issue a credential immediately before one RPC through a shared signer constructed from deployment root material;
- lifetime is positive and no more than 60 seconds;
- not-before cannot be after expiry;
- request fields duplicate applicable claims and must match exactly;
- credential and bearer values are never logged, persisted in Transfer State, returned in responses, or placed in protobuf payload fields.

Authentication and authorization order for every coordinator RPC:

1. read exactly one standard bearer credential;
2. verify syntax, signature, audience, service allowlist, issued/not-before/expiry times, and operation binding;
3. compare credential scope with request Runtime/transfer/attempt/direction/operation/Session/Agent fields;
4. reject before any Transfer State, Runtime Coordination, or S3 access on failure; and
5. execute only the named typed transition.

Missing, malformed, expired, not-yet-valid, wrong-audience, wrong-service, wrong-operation, or scope-mismatched credentials fail closed. Runner credentials cannot authenticate to the coordinator, and trusted coordinator credentials cannot authenticate to Runner Control or Runner Transfer.

The shared coordinator client accepts an injected credential supplier/signer abstraction and adds one bearer credential per call. The library does not read application globals or deployment secrets.

## Interface contract: Runner transfer authorization

Every Runner transfer RPC performs this sequence before reading or sending one file byte:

1. authenticate exactly one Runner bearer credential with `RuntimeRunnerCredentialGrpcAuth`;
2. re-run durable `authorize_runner()` against current Runtime desired generation;
3. parse the opening/request identity and require its Runtime ID to equal the authenticated claim;
4. load the current attempt from `RuntimeTransferStateStore`;
5. reject missing or logically expired state;
6. require exact transfer ID, attempt ID, Runtime ID, desired generation, direction, deadline, and admissible phase;
7. require the identity's accepted Runner generation to equal the generation bound by coordinator dispatch and current Runtime Coordination connection state;
8. acquire a direction-specific per-replica stream permit without an unbounded wait queue;
9. atomically call `claim_stream()` with a fresh claim ID and expected revision; and
10. begin S3 I/O only after the claim succeeds.

A valid Runner credential alone never selects a transfer. Payload identity never selects an object. Duplicate claims, stale desired/accepted generations, opposite directions, wrong attempts, cancelled attempts, expired attempts, and invalid phases fail before first byte.

Terminal attempts are not reopened. An interrupted nonterminal stream requires a new admitted attempt from byte zero; Phase 4 adds no offset-resume protocol.

## Interface contract: download service

`RuntimeRunnerTransferGrpcServicer.DownloadTransfer`:

- acquires the transfer record and transfer-owned object only through state-derived internal identity;
- verifies object metadata before streaming;
- uses `S3Service.iter_object_body()` with the configured 256 KiB maximum chunk size and explicit context-managed close behavior;
- computes authoritative byte count and SHA-256 incrementally while yielding sequential frames;
- records only coalesced bounded progress, never one state mutation per frame;
- checks cancellation, context liveness, deadline, logical expiry, and durable Runner authority between bounded reads;
- sends completion only when read size/hash match the stored trusted manifest;
- never calls `download_bytes()` and never buffers the complete object;
- maps known failures immediately to state settlement and initiating operation correlation;
- releases stream/admission resources idempotently and records cleanup evidence without treating physical cleanup failure as data success or failure authority.

The data RPC does not mark the Runtime destination committed. Phase 5 Runner local verification and atomic publication return bounded commit evidence through Runner Control, after which Control calls `mark_committed()` and settles success.

## Interface contract: upload service

`RuntimeRunnerTransferGrpcServicer.UploadTransfer`:

- authenticates and authorizes from the first opening frame before accepting any chunk;
- creates no S3 multipart upload until authorization and atomic stream claim succeed;
- derives the immutable attempt object from trusted state, never from a Runner field;
- enforces sequential offsets, 256 KiB maximum chunk data, admitted expected size, deadline, logical expiry, cancellation, and one terminal completion declaration;
- incrementally computes authoritative byte count and SHA-256;
- aggregates no more than one 5 MiB multipart part plus one 256 KiB input frame and allows one in-flight part;
- records coalesced progress only;
- validates Runner-declared completion size/hash against authoritative values and trusted expected manifest when present;
- completes and verifies the multipart object only after all checks succeed, then transitions through verification to available;
- uses the verified zero-byte object path for an empty upload;
- aborts incomplete multipart work on protocol failure, integrity failure, cancellation, deadline, stale authority, disconnect, or unexpected error;
- never exposes failed/rejected content as an available object and never retains it for diagnostics;
- returns no object identity to Runner.

Cancellation is caught separately from ordinary exceptions, aborts/cleans up bounded storage work, updates state and operation correlation, releases admission idempotently, and then preserves cancellation semantics.

## Error and terminal mapping

The service uses stable bounded mapping:

| Condition | gRPC status | Transfer classification |
| --- | --- | --- |
| Missing, malformed, or invalid credential | `UNAUTHENTICATED` | `runner_unauthenticated` or `trusted_service_unauthenticated` |
| Runtime, caller, operation, transfer, attempt, direction, or generation scope mismatch | `PERMISSION_DENIED` | `transfer_access_denied` |
| Unknown attempt | `NOT_FOUND` | `transfer_unavailable` |
| Expired, cancelled, terminal, or invalid-phase attempt | `FAILED_PRECONDITION` | `transfer_unavailable` |
| Duplicate stream claim | `ALREADY_EXISTS` | `attempt_already_claimed` |
| Admission, stream permit, chunk, or actual-size limit | `RESOURCE_EXHAUSTED` | `transfer_resource_exhausted` |
| Deadline or logical expiry reached while active | `DEADLINE_EXCEEDED` | `transfer_deadline_exceeded` |
| Caller/context/control-operation cancellation | `CANCELLED` | `transfer_cancelled` |
| Offset, exact length, trusted checksum, or completion mismatch | `DATA_LOSS` | `transfer_integrity_failed` |
| Invalid frame sequence | `FAILED_PRECONDITION` | `transfer_protocol_violation` |
| Internal S3/state failure without a more specific classification | `INTERNAL` | `transfer_stream_failed` |

State settlement remains attempt- and revision-fenced. A late success cannot replace cancellation, expiry, supersession, integrity failure, or another terminal result. Cleanup failure is recorded independently and does not overwrite a committed feature result.

## Interface contract: Runtime Control composition

Phase 4 extends `RuntimeControlSettings` and lifespan composition only as needed to run the two services:

- construct one `RuntimeTransferStateStore` through the Phase 3 factory and the existing Redis client lifecycle;
- construct one process-lifetime async S3 client and `S3Service` using the existing workspace bucket, prefix, optional endpoint, ambient credentials, or explicit configured credentials;
- register Runner Transfer, Transfer Coordinator, existing Runner Control, and existing Provider Control services on the same gRPC server and TLS identity;
- inject state, S3, Runtime Coordination, Runner authenticator, trusted-service authenticator, clock, stream limits, chunk/part limits, and operation-correlation collaborators explicitly;
- close the S3 client, Redis client, database engine, and server deterministically on shutdown;
- preserve the existing Redis-backed `RuntimeCoordinationStore` regardless of transfer backend;
- allow memory Transfer State only as one process-local owner reached through real coordinator and Runner transfer RPCs;
- add no global gRPC message-limit override.

Phase 4 may add backend settings for workspace S3, chunk/part limits, per-replica transfer streams, trusted credential lifetime/skew, and coordinator authentication. Phase 9 owns Helm values, environment propagation, replica validation, endpoint cutover, and production defaults.

## Workstreams and ownership

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Protocol and generated artifacts | `/root/runtime-transfer-implementer` | `proto/azents/runtime_control/v1/`; `python/libs/azents-runtime-control/scripts/generate_proto.py`; generated modules; shared protocol values/tests | This plan | Two typed services, Control intent additions, exact constants, drift-clean generation | library Ruff/format/Pyright/Pytest; generator drift command |
| Trusted coordinator client/auth/service | `/root/runtime-transfer-implementer` | shared coordinator client/value modules; backend credential/auth/coordinator modules and tests | Generated protocol; Phase 3 state | Per-RPC scoped credentials, typed coordinator service, metadata-only state ownership | auth matrix; real coordinator RPC with memory state; no-bytes schema inspection |
| Runner transfer service and storage pipeline | `/root/runtime-transfer-implementer` | backend Runner transfer gRPC modules/tests; focused transfer helpers | Generated protocol; state; S3 primitives | Authenticated/fenced download and upload, bounded hashing/multipart/cancellation | protocol/adversarial tests; >4 MiB real gRPC tests |
| Control intent and Runtime Control composition | `/root/runtime-transfer-implementer` | Runner Control bridge/mapping tests; `control_server.py` and focused tests | Coordinator dispatch; transfer service | Bounded intent/cancel/result correlation and single-owner lifespan wiring | heartbeat concurrency; existing Control regressions; shutdown tests |
| Phase integration and scope verification | `/root` | phase plan, integration inspection, accepted review fixes, git/PR metadata | All workstreams | Verified cohesive Phase 4 diff with no Phase 5+ scope | full command matrix, generator drift, diff/non-goal review, independent cumulative review |

Implementation owner remains `/root/runtime-transfer-implementer`; independent cumulative review remains `/root/runtime-transfer-reviewer`. Neither owner delegates Phase 4 work.

Integration order:

1. add and generate the two new proto services plus Runner Control metadata-only messages;
2. add shared constants, immutable values, schema guards, and coordinator client contract;
3. implement and test coordinator credential signing/authentication independently;
4. implement typed coordinator state operations and bounded intent dispatch;
5. implement Runner transfer per-RPC authorization and stream claim;
6. implement bounded download and upload pipelines over Phase 3 S3 primitives;
7. wire Transfer State and process-lifetime S3 into Runtime Control;
8. add real gRPC default-limit integration and concurrent Control heartbeat evidence;
9. run the complete validation matrix and scope comparison;
10. obtain independent cumulative review and resolve every Critical/Warning finding before push or PR creation.

## Required tests before independent review

### Protobuf and shared library

- generator includes all four proto inputs and a second generation produces no diff;
- generated imports and Pyright exclusions cover every generated module;
- schema descriptor tests prove coordinator messages contain no `bytes` field, chunk type, body field, URL, credential, bucket, or object key field;
- schema descriptor tests prove Runner Control transfer intent/cancel/result messages contain no file bytes or storage authority;
- exact protocol version, capability, audience, maximum chunk size, and message conversion round trips;
- client adds exactly one bearer credential per coordinator RPC and never places it in the request message;
- malformed or empty identity, checksum, direction, timestamp, and terminal values fail before RPC dispatch.

### Trusted coordinator authentication

- missing, duplicate, malformed, tampered, expired, not-yet-valid, overlong-lifetime, wrong-audience, wrong-service, wrong-operation, and mismatched scope credentials fail before state access;
- API and Worker allowed identities succeed only for their signed operation and request scope;
- Runner credential is rejected by coordinator authentication;
- coordinator credential is rejected by Runner Control and Runner Transfer authentication;
- credential values and bearer metadata are absent from logs, responses, state serialization, and exception text;
- injected-clock boundary cases cover exact not-before, expiry, and allowed skew.

### Coordinator service

- a real gRPC client reaches one Runtime Control-owned in-memory Transfer State instance across the RPC boundary;
- unauthorized calls invoke no state, Runtime Coordination, or S3 collaborator;
- admission rejection performs no object allocation, dispatch, or S3 work;
- ready and dispatch validate attempt, revision, direction, Runtime/generation, deadline, and object manifest;
- dispatch binds the current accepted Runner connection generation and appends exactly one metadata-only intent;
- cancellation is persistent/idempotent, orders one bounded cancel message, and promptly correlates terminal operation state;
- verified-object handoff requires upload available state, live expiry, correct consumer scope, and an exclusive claim;
- consumer acknowledge/abandon, settlement, cleanup status, and status reads preserve existing Phase 3 fencing/idempotency;
- no coordinator response exposes a bucket, endpoint, credential, presigned URL, Runner credential, or public product identity.

### Runner transfer authorization and protocol

- unauthorized, stale desired generation, stale accepted Runner generation, wrong Runtime, wrong direction, wrong attempt, wrong phase, cancelled, expired, and terminal requests fail before S3 read/create;
- concurrent duplicate claims allow exactly one stream;
- a same-desired-generation reconnect cannot reopen an already claimed attempt;
- download object missing/metadata mismatch/read failure/midstream cancellation/deadline produces no completion frame;
- download chunks use exact offsets, remain at or below 256 KiB, hash correctly, close S3 body on every exit, and never call `download_bytes()`;
- upload rejects chunk-before-open, duplicate open, empty chunk, oversized frame, offset gap/reorder/duplicate, exceeded admitted size, missing/repeated completion, data after completion, truncated body, Runner checksum mismatch, and trusted checksum mismatch;
- upload cancellation, deadline, disconnect, part failure, completion failure, verification failure, and stale authority abort multipart work and leave no available object;
- zero-byte download and upload complete through their explicit valid paths;
- Runtime Control actual upload size/SHA-256 are authoritative and are the only values published to state;
- progress is monotonic/coalesced and never persisted once per chunk;
- state settlement and cleanup remain attempt/revision fenced under late frames and cancellation races.

### Control correlation and regression

- transfer intent, cancellation, and result correlation use no Runtime Coordination body stream and never append `RunnerBodyChunk`;
- a known transfer failure finalizes the initiating operation promptly rather than waiting for its generic timeout;
- existing ordinary Runner operation request/body/reply behavior remains unchanged;
- existing Provider and Runner registration/authentication/generation tests remain green;
- heartbeat and one bounded ordinary operation complete while a transfer stream is flow-controlled;
- Runtime Control lifespan creates exactly one Transfer State owner and one process-lifetime S3 client, and closes both correctly;
- memory Transfer State still coexists with Redis Runtime Coordination; selecting memory never creates state in API/Worker code.

### Real default-limit gRPC integration

Run an actual `grpc.aio.server()` and real channels without message-size options:

- authenticate a synthetic Runner and maintain a registered `ConnectRunner` stream;
- transfer deterministic content larger than 4 MiB in each direction through the new RPC;
- assert exact final size and SHA-256;
- inspect every observed frame and assert serialized message size remains bounded independently from complete file size;
- send concurrent Runner heartbeat traffic and complete one bounded ordinary operation while transfer backpressure is active;
- assert the Control stream remains registered and receives its heartbeat acknowledgement;
- repeat cancellation and malformed-frame cases and prove only the transfer RPC/attempt fails;
- assert no `RESOURCE_EXHAUSTED` message-size failure and no global gRPC limit override.

The synthetic Runner may use bounded in-memory/disk test fixtures, but production local filesystem snapshot, temp-file, fsync, overwrite race, and atomic commit behavior remain Phase 5.

## Validation commands

```bash
cd python/libs/azents-runtime-control
uv sync
uv run python scripts/generate_proto.py
git diff --exit-code -- src/azents_runtime_control/proto
uv run ruff check .
uv run ruff format --check .
uv run pyright .
uv run pytest -vv
```

```bash
cd python/apps/azents
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright .
uv run pytest -vv \
  src/azents/core/runtime_transfer_coordinator_credential_test.py \
  src/azents/runtime/control_protocol/grpc \
  src/azents/runtime/transfer \
  src/azents/runtime/control_server_test.py
```

The exact new test filenames may vary, but the executed selection must include every Phase 4 auth, coordinator, Runner transfer, Control correlation, composition, and real gRPC integration test plus the existing affected Runner/Provider Control regression suites.

Also run:

```bash
git diff --check
```

Run pre-commit on every changed file before commit. Docker-backed Redis/RustFS coverage may be unavailable locally; report that environment limitation explicitly and rely on required CI rather than claiming a local pass. The real default-limit gRPC suite must not require Docker and must not skip.

## Independent review criteria

`/root/runtime-transfer-reviewer` reviews the cumulative Phase 4 diff after primary validation. A PASS requires:

- generated protocol exactly matches this plan and contains no data/control or trusted/untrusted authority leak;
- no global gRPC message-limit increase;
- every Runner data RPC reauthenticates and rechecks durable generation before first byte;
- transfer/attempt/direction/deadline/phase/accepted-generation fencing and atomic claim are complete;
- coordinator credentials are short-lived, audience/service/operation/scope bound, and non-interchangeable with Runner credentials;
- coordinator calls fail before state access when unauthorized and never carry bodies;
- upload/download memory and message bounds are calculable and independent from complete file size;
- S3 body closure, multipart abort, cancellation, deadline, and terminal state behavior are correct;
- Runtime Control is the sole Transfer State owner while Runtime Coordination remains Redis-backed;
- known failures correlate promptly to the initiating operation;
- the >4 MiB real gRPC test uses default limits and preserves Control heartbeat responsiveness;
- no Phase 5 Runner filesystem, Phase 6/7/8 consumer, Phase 9 Helm/cutover, Phase 10 E2E, or Phase 11 spec-promotion work is present.

## Scope-drift check

Compare the final diff with this plan and the Phase 4 section of the multi-phase plan. Reject or move to its later phase:

- production Runner transfer channel, snapshot, staging file, fsync, atomic replacement, overwrite, or source-mutation implementation;
- Exchange, Artifact, VFS, Slack, `present_file`, External Channel, or provider consumer migration;
- Helm values/templates, NetworkPolicy, lifecycle rules, deployment replica validation, or production endpoint propagation;
- mixed-version routing, compatibility adapters, capability fallback, or legacy inline-binary fallback;
- generic gRPC message-limit changes;
- Runner-visible S3 bucket/key/URL/credential/object handle or direct storage SDK access;
- transfer bytes in Runner Control, coordinator protobuf, Redis coordination, Transfer State, logs, metrics, or operation metadata;
- direct API/Worker access to `RuntimeTransferStateStore`;
- replacement of the existing Redis-backed Runtime Coordination Store;
- living-spec promotion before the planned Phase 11 review.

## Handoff contract

The implementation owner receives and must follow:

- `docs/azents/requirements/transfer-260725-runtime-file-transfer.md`
- `docs/azents/adr/transfer-260725-runtime-file-transfer.md`
- `docs/azents/design/transfer-260725-runtime-file-transfer.md`
- `docs/azents/plans/runtime-file-transfer-implementation-plan.md`
- this phase execution plan
- current Agent Runtime Control living spec
- root and Python project instructions plus applicable convention bodies

Any missing detail that changes a protobuf field, credential claim, trust boundary, state authority, object-handle exposure, byte/message bound, terminal authority, or phase scope must be reported to `/root` before implementation continues. Private helper structure and test file organization may be selected autonomously inside these fixed contracts.
