---
title: "Runtime File Transfer"
created: 2026-07-25
tags: [architecture, runtime, files, transfer, grpc, s3, security]
document_role: primary
document_type: adr
snapshot_id: transfer-260725
---

# transfer-260725/ADR: Runtime File Transfer

## Requirements

This ADR records hard-to-reverse architecture decisions for the confirmed [Runtime File Transfer Requirements](../requirements/transfer-260725-runtime-file-transfer.md) (`transfer-260725/REQ`).

All architecture decisions in the completed backlog are accepted and recorded below.

## Context

Complete-file transfer currently crosses the Runner Control protocol as operation payloads or operation events. Request bodies are chunked in the coordination layer, stored as Base64 JSON in Redis, and then reassembled into one protobuf `RunnerOperationRequest` before delivery. Runtime file reads similarly return Base64 file events that are joined into one application `bytes` result. This couples file size to control-message size and caused a 6 MiB Slack attachment transfer to exceed the default 4 MiB gRPC receive limit.

The confirmed requirements establish Runtime Control as the trusted transfer gateway. Runtime Runner is an external, potentially manipulated component. The Runner must not receive object-storage credentials, presigned URLs, bucket names, object keys, or provider topology. File bytes must use a dedicated streaming RPC contract with a failure boundary independent from the long-lived Runner Control stream. Worker and Runner must not establish a direct binary connection.

The requirements also establish the existing S3-compatible workspace storage as the trusted internal object boundary. When an authorized source already exists as an internal object and the next trusted destination is another internal object, unchanged bytes must move through object-store-native copy, promotion, or equivalent reference semantics rather than an application download and re-upload.

## Current System Evidence

### Runner Control rebuilds complete files at the gRPC boundary

`RuntimeRunnerFileStorage.put()` accepts a complete `bytes` value and calls `write_file()`. The coordination implementation stores request body chunks in Redis Streams as Base64 JSON, but `RuntimeRunnerControlGrpcServicer._runner_operation()` reads every body chunk and appends all of them to one `RunnerOperationRequest.body_chunks` collection. The resulting protobuf message remains proportional to the complete file size.

`RuntimeRunnerFileStorage.get()` calls `read_file(max_bytes=None)` and returns one complete application `bytes` value. Runner file events use Base64 payloads, and the operation client joins the returned chunks before the caller receives the result. `read_range()` bounds one call but performs repeated ordinary control operations rather than providing a distinct file-transfer data plane.

### Existing feature paths relay complete bytes through application memory

External Channel inbound download streams Slack HTTP data into a `bytearray`, converts it to `bytes`, and passes the complete body to `FileStorage.put()`. `import_file` resolves Exchange, Artifact, and managed-file resources into a complete `ImportResolvedFile.body` before calling the same storage path. `present_file` reads the complete Runtime file and supplies the body to Exchange creation.

Outbound External Channel publication performs bounded ranged reads, but each range still crosses the Runner Control operation contract and the provider path does not share a common complete-file transfer lifecycle.

### Existing object storage can support the trusted staging boundary

The server already uses one S3-compatible workspace bucket through `S3Service`. It supports upload, download, delete, copy, and move operations. Upload accepts a file-like body, while download currently reads the complete response body. A transfer implementation therefore needs bounded streaming object reads, multipart or streaming writes, checksum metadata, and explicit abort and cleanup operations rather than a new storage system.

Runtime Control receives the shared workspace S3 endpoint, bucket, and credential environment through the Helm deployment, but its settings and lifespan do not currently construct an S3 client. Runner Pods do not receive those storage credentials, which matches the required trust boundary.

### Existing Runner authentication is reusable but transfer authorization is missing

The Runner stream authenticates a signed bearer credential bound to one Runtime ID and desired generation, rechecks durable authorization, and registers a current Runner connection generation. A transfer RPC can reuse the credential authentication mechanism, but each transfer stream must additionally bind and validate transfer ID, Runtime ID, current Runner generation, direction, admitted size, and terminal state. A transfer stream must not rely only on the existence of the long-lived control connection.

### Coordination storage is appropriate for bounded metadata, not file bodies

The Redis coordination layer already provides TTL-backed shared request, reply, operation, and connection state across Runtime Control replicas. It is suitable for bounded transfer manifests and state transitions. Relaying transfer bytes through Redis would retain the current Base64 expansion, memory pressure, and lifecycle coupling and is excluded by the requirements.

## Requirements-Fixed Boundaries

The following are fixed by `transfer-260725/REQ` and are not open ADR choices:

1. File bytes cross the Runtime boundary only through a dedicated transfer streaming RPC terminated by Runtime Control.
2. Runner Control requests, replies, Redis coordination streams, and operation events do not carry file bytes.
3. Runtime Control owns internal storage access; Runner receives no S3 implementation details or authority.
4. Worker and Runner do not establish a direct binary connection.
5. Both Server-to-Runtime and Runtime-to-server complete-file transfer use the common capability.
6. Existing S3 objects move to other internal object destinations through object-store-native copy, promotion, or equivalent trusted reference semantics.
7. The first delivery may retry from byte zero and does not require offset resume.
8. Adopted consumers do not fall back to the legacy inline-binary transfer path.

## Decision Backlog (Completed)

### D1. Data-plane isolation topology — Accepted

Choose whether the transfer service shares the Runtime Control deployment and endpoint while using a separate gRPC service and dedicated Runner channel, or uses a separate port or deployment for stronger physical resource isolation.

**Dependencies:** None. This determines the process, deployment, TLS, service-discovery, autoscaling, and failure-isolation boundary for later decisions.

### D2. Transfer staging object model — Accepted

Choose whether every transfer obtains an immutable object in a transfer-owned temporary namespace, or whether existing authorized S3 sources can be referenced directly and copied only when lifecycle or consistency requires a snapshot.

**Dependencies:** D1. This determines source-lifetime isolation, copy cost, cleanup ownership, and retry behavior.

### D3. Final product-file publication ownership — Accepted

Choose whether the transfer layer stops at a verified temporary object and existing Exchange, Artifact, or other feature services own final object copy and metadata publication, or whether the transfer layer directly creates product file resources.

**Dependencies:** D2. This determines whether transport remains independent from product file identity, authorization, preview, metadata, and retention semantics.

### D4. Transfer state authority and lifetime — Accepted

Choose whether shared Redis metadata plus object-store state is authoritative for active and recently terminal transfers, or whether transfers require a durable relational entity and history.

**Dependencies:** D2 and D3. This determines replica failover, idempotency, terminal retention, reconciliation, and cleanup mechanisms.

### D5. Data retention and cleanup policy — Accepted

Choose the deletion and retention policy for successful, failed, cancelled, expired, and
abandoned transfer objects; whether any content grace period is allowed for retry; how
long bounded terminal metadata remains available; and how explicit cleanup, orphan
reconciliation, and object-storage lifecycle rules divide responsibility. The fixed
source-retention ceiling from the Requirements and D2 cannot be relaxed.

**Dependencies:** D2 through D4. This determines how long transfer content and metadata
survive after each terminal outcome and which cleanup evidence is authoritative.

### D6. Directional RPC handshake — Accepted

Choose between typed Runner-initiated `DownloadTransfer` and `UploadTransfer` RPCs, or one generic bidirectional frame stream. The Runner must initiate data RPCs because it maintains outbound connectivity to Runtime Control.

**Dependencies:** D1 and D4. This determines the versioned external Runner contract and stream state machines.

### D7. Integrity, atomic commit, and retry contract — Accepted

Choose the trusted checksum and actual-byte authorities, Runtime temporary-file and atomic-rename behavior, S3 multipart completion rules, duplicate-attempt fencing, and retry-from-zero identity semantics.

**Dependencies:** D2, D4, D5, and D6. This determines when either destination can be reported successful.

### D8. Admission, backpressure, and resource isolation — Accepted

Choose where per-Runtime and deployment-wide transfer admission, active-stream limits, in-flight byte limits, bounded buffers, multipart concurrency, and control-traffic protection are enforced.

**Dependencies:** D1, D6, and D7. Numeric defaults remain reversible configuration and are not requester decisions.

### D9. Protocol rollout and mixed-version handling — Accepted

Choose the capability and protocol-version cutover contract for Control, Runner, and feature consumers, including whether mixed deployments may route only to transfer-capable Runners or fail the operation immediately.

**Dependencies:** D6 through D8. Legacy inline-binary fallback remains excluded.

## Preliminary Feasibility

| Area | Result | Evidence and gap |
| --- | --- | --- |
| Dedicated Runner transfer RPC | Feasible | The protobuf library and gRPC server already support additional services; a new service and Runner stub are required. |
| Runner authentication | Feasible | Runtime-bound signed credentials and current-generation authorization already exist; transfer-scoped binding is missing. |
| Independent data channel | Feasible | Runner already creates outbound gRPC channels; a dedicated transfer channel can use the same TLS and bearer material. |
| S3-compatible staging | Conditional | Runtime Control receives object-storage configuration, but needs settings, client lifespan, streaming read, multipart write, and cleanup support. |
| S3-to-S3 movement | Feasible | `S3Service.copy()` already exists; product services need object-reference creation paths and compensation semantics. |
| Bounded provider ingestion | Conditional | Slack already exposes an async HTTP byte iterator but currently accumulates it; the consumer API must accept a bounded stream or transfer sink. |
| Runtime atomic destination | Conditional | Runner workspace operations exist, but transfer-specific temporary paths, checksum verification, and atomic replacement are missing. |
| Shared transient state | Feasible | Redis coordination already provides replica-shared TTL state, generation fencing patterns, and operation metadata, but no transfer state machine. |
| Product publication from object | Conditional | Exchange and Artifact services currently accept complete `bytes`; they need trusted object-source copy and bounded preview or transformation paths. |
| E2E verification | Feasible | Existing External Channel and file-lifecycle E2E suites provide fixtures; they need a file larger than the control message limit and transfer diagnostics. |

No repository evidence blocks the confirmed requirements. The main design work is defining the external Runner streaming contract, trusted temporary-object lifecycle, and publication ownership without reintroducing whole-file application buffers.

## Decisions

### transfer-260725/ADR-D1: Co-locate the transfer service by default behind an independently configurable endpoint and dedicated Runner channel

**Affected requirements:** `transfer-260725/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`,
`REQ-6`, `REQ-8`, `REQ-9`

Runtime Control terminates a separate versioned Runner transfer gRPC service. The
default deployment serves that service from the existing Runtime Control process and
endpoint, using the existing TLS server identity and Runtime-bound Runner credential
authentication.

Runner uses a dedicated transfer stub and channel rather than sending transfer RPCs on
the channel that owns the long-lived `ConnectRunner` stream. Channel configuration must
preserve an independent underlying HTTP/2 connection so transfer stream rejection,
cancellation, or connection loss does not directly close the Runner Control stream.

The transfer endpoint is independently configurable from the control endpoint even when
both initially resolve to the same Runtime Control Service. This preserves the external
Runner RPC contract and allows operators to move transfer traffic to a separate
deployment later by changing endpoint and deployment configuration rather than
redesigning the protocol.

The co-located implementation must enforce transfer-specific admission, concurrency,
buffer, and downstream-storage budgets. Those resource policies are finalized by a later
decision; co-location does not allow transfer work to consume unbounded shared process
resources.

**Rejected alternatives**

- A second listener or port in the same Pod adds certificate, Service, probe, and network
  configuration while retaining the same process failure and resource boundary.
- A separate transfer deployment from the first release provides stronger physical
  isolation but duplicates deployment, scaling, trust, database, Redis, S3, and
  observability configuration before measured transfer load requires it.
- Carrying transfer streams on `ConnectRunner` or its channel contradicts the confirmed
  independent failure-boundary requirement.

**Consequences**

- The first release minimizes deployment complexity and reuses current Runtime Control
  authentication and TLS configuration.
- Transfer RPC failures and flow control are isolated from the long-lived control
  connection, but CPU, memory, event-loop, and process failure remain shared until an
  operator selects a separate transfer deployment.
- Runtime and Helm configuration gain an independent transfer endpoint even when its
  default value is the control endpoint.

### transfer-260725/ADR-D2: Snapshot every transfer into an immutable transfer-owned temporary object

**Affected requirements:** `transfer-260725/REQ-1`, `REQ-2`, `REQ-4`, `REQ-5`,
`REQ-6`, `REQ-7`, `REQ-9`, `REQ-10`

Every admitted complete-file transfer owns one immutable temporary object for each
attempt in a transfer-specific internal object-storage namespace.

For Server-to-Runtime transfer, a trusted feature service first authorizes and resolves
the source. When the source already exists in internal S3-compatible storage, it creates
the transfer snapshot through an object-store-native copy rather than downloading and
re-uploading the body. When the source is an external provider or another streamed
source, the trusted adapter writes bounded chunks into the transfer object while
enforcing actual-byte limits and integrity metadata.

For Runtime-to-server transfer, Runtime Control creates a new transfer object and writes
the authenticated Runner stream into it. The object becomes a complete transfer snapshot
only after actual size, ordering, integrity, and object-upload completion checks succeed.

A transfer object is never overwritten, appended to by a later attempt, or reused for a
different transfer direction. Retry from byte zero creates a new attempt object and
generation-fences the prior attempt. Runtime Control reads and writes only transfer-owned
objects during Runner data exchange; it does not need Runner-visible knowledge of
Exchange, Artifact, provider, or other product storage identities.

The transfer expiration time cannot exceed the earlier of the configured temporary
transfer lifetime and the authoritative source's remaining product retention. Success,
failure, cancellation, timeout, and supersession trigger explicit cleanup. An
object-storage lifecycle rule provides a final defense for abandoned objects and
incomplete multipart uploads rather than serving as the primary completion mechanism.

**Rejected alternatives**

- Reading an existing Exchange, Artifact, or other product object directly avoids one
  object copy but couples active transfer correctness to source deletion, expiration,
  mutation, authorization, and service-specific lease behavior.
- A conditional direct-reference model requires a durable classification of which source
  types are immutable and sufficiently pinned. It creates different retry and failure
  semantics by source type and makes future source integrations harder to verify.
- Relaying an existing object through application bytes before staging contradicts the
  object-store-native movement requirement.

**Consequences**

- Every Runtime data exchange uses one uniform object snapshot and transfer state
  machine, independent of the original source type.
- Retries and Runner streams observe a stable byte sequence even if the product source
  later expires or is deleted within its existing lifecycle.
- Existing S3 sources incur an additional internal object copy, temporary storage, and
  cleanup work.
- Product services retain source authorization and lifecycle authority, while the
  transfer layer owns only attempt-scoped temporary objects.

### transfer-260725/ADR-D3: Keep transfer completion product-agnostic and let feature services own final publication

**Affected requirements:** `transfer-260725/REQ-1`, `REQ-2`, `REQ-5`, `REQ-6`,
`REQ-7`, `REQ-8`, `REQ-9`, `REQ-10`

The transfer layer owns authorization binding for one transfer attempt, temporary-object
creation, Runtime streaming, actual-byte and integrity verification, terminal transfer
state, and cleanup coordination. A successful Runtime-to-server transfer produces a
verified internal transfer-object handle for a trusted consumer. That handle is never
exposed to the Runner, model, public API, or user.

Existing feature services retain responsibility for their final outcomes:

- Exchange and Artifact services preallocate their product identity and final object key,
  revalidate user, Session, Agent, and Workspace ownership, copy the verified transfer
  object to the final key, perform product-specific preview or transformation work,
  commit metadata, and compensate uncommitted final objects on failure.
- External Channel adapters stream the verified transfer object to the authorized
  provider and retain their existing provider delivery and action-completion semantics.
- Server-to-Runtime source services retain source authorization and create the immutable
  transfer snapshot before Runtime Control begins Runner delivery.

Transfer completion and feature completion are distinct. A verified temporary object
means the Runtime boundary transfer succeeded; it does not by itself mean that
`present_file`, Artifact creation, or provider publication succeeded. The caller reports
success only after its feature-owned final publication contract completes.

The trusted consumer acknowledges whether it consumed or abandoned the transfer object.
The exact successful, failed, cancelled, and unacknowledged retention windows are
finalized by the data-retention decision.

**Rejected alternatives**

- Letting Runtime Control create Exchange, Artifact, or other product resources couples
  the external Runner transport to product identity, authorization, previews, database
  transactions, and retention policies.
- Feature-specific finalizer callbacks hosted by the transfer service preserve apparent
  centralization but create ambiguous retry, transaction, dependency, and cleanup
  ownership inside Runtime Control.
- Treating transfer completion as automatic feature success can expose an object that was
  never published or delivered through its owning feature contract.

**Consequences**

- The Runner transfer contract remains stable as product file types and provider adapters
  evolve.
- Existing feature services require object-source publication methods in addition to
  their current complete-`bytes` methods.
- Callers must model the handoff from verified transfer object to feature completion and
  acknowledge the transfer object after publication or abandonment.
- Preview generation and content transformation remain feature-owned bounded pipelines,
  not transport responsibilities.

### transfer-260725/ADR-D4: Own transient transfer state through an interface with Redis and in-memory implementations

**Affected requirements:** `transfer-260725/REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`,
`REQ-8`, `REQ-9`, `REQ-11`

Transfer state authority is the `RuntimeTransferStateStore` contract rather than Redis,
an object-storage record, or a relational transfer entity. The contract owns atomic
attempt creation, lookup, state transition, generation and attempt fencing, heartbeat,
cancellation, terminal settlement, consumer acknowledgement, and expiration discovery.
It stores only bounded manifests and state metadata, never file-body chunks.

The first delivery provides at least two conforming implementations:

- a Redis-backed implementation for multi-replica Runtime Control deployments that need
  shared transfer authority and cross-replica failover; and
- a process-local in-memory implementation for standalone single-process deployments,
  local development, and deterministic tests.

Both implementations run through the same contract-test suite. Runtime composition
selects the backend through configuration rather than constructing Redis directly inside
transfer business logic. The existing Runtime coordination Protocol, Redis and memory
implementations, and shared contract-test pattern provide the repository precedent, but
transfer state retains a dedicated contract and state machine.

The in-memory implementation is valid only when one Runtime Control process owns all
transfer state. Deployment configuration must reject or otherwise prevent multiple
Runtime Control replicas from independently using process-local state. Process restart
loses active and recently terminal in-memory records; affected work fails closed and
owned temporary objects enter explicit or lifecycle-backed orphan cleanup.

The Redis implementation is authoritative only through the same interface. Redis is not
a required standalone deployment component, and transfer behavior must not depend on
Redis-specific stream, key, or serialization details outside its adapter.

S3 object existence is byte evidence, not state authority. When the selected state store
has no valid transfer record, Runtime Control never infers transfer success from an
orphan object. Long-term operational evidence remains in structured logs and metrics,
while product publication remains authoritative in its owning feature service under D3.

**Rejected alternatives**

- Hard-coding Redis into transfer services makes an optional infrastructure component a
  product requirement and prevents standalone operation.
- A relational transfer row adds a durable product-like entity and database lifecycle
  for short-lived transport state without a confirmed audit or user-history requirement.
- Redis for active state plus a relational terminal summary introduces a dual-write
  handoff and ambiguous authority while feature-owned durable outcomes already exist.
- Treating S3 object metadata as the transfer state machine cannot provide the required
  atomic authorization, cancellation, fencing, and consumer acknowledgement semantics.

**Consequences**

- Standalone deployments and tests can run transfers without Redis.
- Multi-replica deployments require the shared Redis implementation or a future
  implementation with equivalent distributed coordination semantics.
- Runtime Control composition must stop hard-coding
  `RedisRuntimeCoordinationStore` where a configured process-local backend is valid.
- In-memory restart recovery is intentionally fail-closed; D5 defines how its abandoned
  transfer objects and remaining metadata are retained and cleaned.

### transfer-260725/ADR-D5: Use a one-hour logical TTL with immediate best-effort content cleanup

**Affected requirements:** `transfer-260725/REQ-4`, `REQ-5`, `REQ-6`, `REQ-8`,
`REQ-9`, `REQ-10`, `REQ-11`, `REQ-12`

Transfer content is retained only while one active attempt or its trusted feature
consumer still requires it. Every attempt has an immutable logical expiration no later
than one hour after attempt creation and no later than the authoritative source's earlier
expiration. Heartbeats, retries, state transitions, and consumer activity do not extend
that absolute deadline.

Server-to-Runtime success treats the Runner's verified atomic destination commit as the
consumer acknowledgement. Runtime-to-server success retains the verified transfer object
only until the D3 feature owner acknowledges final object publication or provider
delivery. A feature consumer may retry its final publication while the original attempt
remains unexpired and unacknowledged, but cannot revive or extend an expired attempt.

Success, failure, cancellation, timeout, integrity rejection, supersession, and consumer
abandonment immediately invalidate the transfer and trigger best-effort object deletion
or multipart abort. Physical cleanup failure does not reverse a successfully committed
Runtime file, product object and metadata transaction, or provider delivery. It records
bounded `cleanup_pending` evidence and schedules asynchronous retry while state remains
available.

Object existence never overrides logical expiration. Runtime Control and trusted feature
consumers reject an expired transfer even when the physical object remains in
S3-compatible storage. Content-free terminal metadata expires no later than one hour
after terminal settlement.

Object-storage lifecycle configuration is a coarser final defense for orphan objects and
incomplete multipart uploads. It uses the shortest portable backend-supported interval
for the transfer prefix, but it does not define or delay the synchronous one-hour
authorization boundary. Explicit multipart abort and object delete remain the normal
cleanup path.

**Rejected alternatives**

- Keeping successful content for a fixed post-publication grace period duplicates files
  after their owning feature no longer needs the transfer snapshot and can extend
  effective retention.
- Keeping failed or rejected Runner content for diagnostics retains potentially
  manipulated or sensitive bytes and turns the transfer namespace into a quarantine
  store.
- Making physical object deletion part of feature success allows a temporary storage
  cleanup outage to change an already completed user or provider result into failure.
- Using only object-storage lifecycle expiration cannot enforce the one-hour logical
  access boundary consistently across S3-compatible backends.

**Consequences**

- The normal path deletes content immediately after settlement, while one hour is an
  absolute safety ceiling rather than a standard retention duration.
- A failed physical delete remains observable but does not affect the completed feature
  result.
- Publication retry after consumer acknowledgement or logical expiration requires a new
  transfer attempt.
- An in-memory state loss can leave an orphan object without a cleanup record; prefix
  reconciliation and lifecycle configuration remain required defenses.

### transfer-260725/ADR-D6: Use separate Runner-initiated typed RPCs for download and upload

**Affected requirements:** `transfer-260725/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`,
`REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`, `REQ-9`

The versioned Runner transfer service exposes two direction-specific RPCs:

- `DownloadTransfer` accepts one bounded request and returns a server stream of raw byte
  chunks for Server-to-Runtime transfer.
- `UploadTransfer` accepts a client stream containing one opening frame followed by raw
  byte chunks and returns one verified result for Runtime-to-server transfer.

Runner initiates both RPCs through the dedicated D1 transfer channel after receiving a
small transfer intent through Runner Control. The intent identifies the transfer,
attempt, direction, authorized Runtime path, expected metadata, operation correlation,
and deadline but contains no file bytes or object-storage details.

Every data RPC reauthenticates the Runner credential and binds the request to the current
Runtime, Runner generation, transfer ID, attempt ID, direction, state, and deadline.
Possession of a valid Runner credential does not authorize another transfer or the
opposite direction.

`DownloadTransfer` sends only direction-specific chunk messages. Runner writes those
chunks to a temporary Runtime path and reports its final destination commit through
bounded control status after the data stream finishes. `UploadTransfer` requires an
opening identity frame before any chunk and returns only after Runtime Control has
verified and settled the object upload. A Runner control result cannot override a
conflicting authoritative transfer-store result.

Chunk data uses protobuf `bytes`, not Base64, JSON, Redis streams, repeated fields in one
complete-file request, or the long-lived `ConnectRunner` stream. One transfer attempt
owns one independent data RPC. The first delivery does not multiplex multiple transfers
over one persistent data stream and does not resume an interrupted RPC from an offset.

Common identity, error, and bounded metadata messages may be shared between the two RPC
schemas, but their valid frame types and state transitions remain direction-specific.

**Rejected alternatives**

- One generic bidirectional `TransferFrame` RPC permits many invalid direction and phase
  combinations, expands the untrusted message state machine, and obscures the different
  completion authorities for upload and download.
- One persistent Runner data stream multiplexing multiple transfers recreates a shared
  failure and backpressure boundary and requires a custom stream-level multiplexing
  protocol.
- Sending transfer chunks through the Runner Control stream or Redis coordination
  contradicts the confirmed binary/control separation.

**Consequences**

- Upload and download authorization, flow control, validation, cancellation, and error
  mapping can be implemented and tested independently.
- The protobuf surface contains two RPC methods and direction-specific frames instead of
  one generic method.
- Runner Control remains responsible for operation intent and lifecycle correlation,
  while the transfer RPC and transfer store remain authoritative for data-path success.
- D7 defines chunk sequencing, checksum authority, atomic destination publication, and
  retry fencing within these RPC shapes.

### transfer-260725/ADR-D7: Require SHA-256, exact length, sequential offsets, atomic publication, and attempt-fenced retry

**Affected requirements:** `transfer-260725/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`,
`REQ-5`, `REQ-6`, `REQ-8`, `REQ-9`, `REQ-10`, `REQ-12`

Every transfer attempt has an expected size, an optional trusted expected SHA-256 when
the source already provides one, an actual size and SHA-256 computed at the trusted
boundary, and a strictly monotonic byte offset. A chunk is valid only when its offset
equals the next expected offset and its length remains within the admitted remaining
bytes. Duplicate, omitted, reordered, trailing, oversized, or late chunks fail only that
attempt.

For Server-to-Runtime transfer, Runtime Control reads the immutable D2 snapshot while
computing its actual size and SHA-256 and sends bounded raw chunks to Runner. Runner
independently computes size and SHA-256 while writing to an attempt-owned temporary file.
Runtime Control sends terminal completion metadata only when its object read satisfies
the admitted manifest. Runner publishes the destination only when its independently
computed result matches that completion metadata.

The Runtime temporary file resides on the same filesystem as the destination so commit
uses an atomic replacement primitive. The Runner rechecks destination and overwrite
policy immediately before commit. With replacement disabled, an existing destination
causes failure. With replacement enabled, the previous valid destination remains
unchanged until the verified temporary file can atomically replace it. Any verification
or commit failure removes only the temporary attempt path.

For Runtime-to-server transfer, Runner-declared size and checksum are untrusted
validation inputs. Runtime Control enforces the admitted expected size against actual
received bytes, computes the authoritative SHA-256, rejects trailing or truncated data,
and completes the object upload only after all checks succeed. Multipart completion
therefore marks one verified transfer object; an incomplete, failed, cancelled, or
superseded attempt is aborted and never exposed to a feature consumer.

The logical `transfer_id` identifies the feature operation, while each byte-transfer try
uses a new immutable `attempt_id`, transfer object, and Runtime temporary path. The state
store atomically permits only one active data RPC for an attempt. Retry from byte zero
creates a new attempt and fences the previous one. A late frame, completion, control
event, or cleanup action for an older attempt cannot settle or delete the newer attempt.

A terminal attempt is idempotent. Reopening it does not replay bytes or repeat destination
publication; the service returns its bounded terminal result or a deterministic terminal
error. The first delivery does not reuse multipart parts or Runtime byte offsets after an
interruption.

SHA-256 is the required cross-backend checksum. S3-native checksums may provide
additional validation but do not replace the common actual SHA-256 and size recorded by
the trusted transfer boundary. Checksums and byte counts may appear in bounded structured
diagnostics; file contents do not.

**Rejected alternatives**

- Using S3 ETag or a backend-native checksum as the sole common authority depends on
  multipart and S3-compatible backend semantics and does not verify the Runtime
  destination contract.
- Trusting Runner-reported size or checksum allows a manipulated Runner to settle data
  that Runtime Control did not independently receive and verify.
- Checking only byte length cannot detect same-length corruption, wrong source
  resolution, duplication, or chunk assembly defects.
- Writing directly to the final Runtime destination exposes partial content and can
  destroy a previous valid destination before verification completes.
- Resuming the same attempt from multipart parts or Runtime offsets adds a persistent
  partial-state protocol that is not required by the first delivery.

**Consequences**

- Runtime Control and Runner both spend CPU on incremental SHA-256 for
  Server-to-Runtime transfer; Runtime Control is the authoritative checksum owner for
  Runtime-to-server transfer.
- Runner needs attempt-owned temporary-file and atomic-replacement support.
- Feature services publish actual size and SHA-256 from the verified transfer object
  rather than recomputing by downloading the complete object.
- Verification or atomic commit failure is a transfer failure. D5 best-effort cleanup
  may not reverse success, but it never converts failed verification or publication into
  success.

### transfer-260725/ADR-D8: Admit transfers explicitly and enforce bounded per-Runtime, per-replica, and deployment-wide resources

**Affected requirements:** `transfer-260725/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`,
`REQ-6`, `REQ-8`, `REQ-9`, `REQ-11`, `REQ-12`

Runtime Control acquires an atomic admission lease before creating or activating a
transfer attempt. Admission validates the applicable product and provider file-size
policy, remaining transfer TTL and deadline, per-Runtime active transfers and admitted
bytes, per-replica active data streams, deployment-wide transfers, direction-specific
limits, and S3 copy or multipart concurrency.

The D4 state-store contract owns bounded admission and lease semantics. A Redis
implementation coordinates deployment-wide limits across replicas. The in-memory
implementation enforces the same contract within its supported single-process
deployment. Every lease expires and can be reclaimed after process loss; success,
failure, cancellation, timeout, and supersession release it idempotently.

Runtime Control does not maintain an unbounded pending transfer queue. When admission is
unavailable, it returns an immediate explicit retryable resource-exhaustion result before
creating a byte-transfer attempt. Per-Runtime limits apply before global limits so one
Runtime cannot consume the complete deployment budget. A retry acquires a new admission
lease before allocating an attempt object or opening a data RPC.

Every producer and consumer uses bounded incremental flow:

- gRPC upload and download retain only a configured small number of chunks;
- S3 reads do not prefetch the complete object;
- multipart uploads retain only bounded part buffers and cap in-flight part requests;
- provider adapters consume or produce bounded streams; and
- no state-store implementation contains transfer bytes.

Transfer work uses dedicated upload, download, checksum, object-copy, and multipart
budgets rather than the semaphores that route Runner heartbeat, cancellation, lifecycle,
and ordinary bounded control operations. Cancellation and deadline propagation stop
further reads and writes, settle state, release admission, and trigger D5 cleanup.

The concrete chunk size, multipart part size, buffer depth, per-Runtime concurrency,
replica concurrency, and deployment limits are reversible operational configuration
rather than fixed ADR values. Their validation must make the maximum process memory and
in-flight object-storage work calculable.

Structured metrics expose active streams, admitted and in-flight bytes, admission
latency, rejection reason, per-direction throughput, transfer duration, cancellation,
deadline, checksum cost, object-storage latency, and cleanup outcomes. A known overload
reaches the caller as an explicit transfer result rather than a later generic operation
timeout.

**Rejected alternatives**

- Relying only on gRPC or HTTP flow control bounds one producer-consumer path but does not
  limit the aggregate number of streams, buffers, checksum tasks, or multipart requests.
- An unbounded in-process queue converts overload into memory growth and deadline expiry.
- A mandatory external transfer job queue and worker pool adds another infrastructure
  component and coordination lifecycle before measured throughput requires a separate
  D1 deployment.
- Sharing ordinary Runner Control concurrency budgets allows bulk transfer traffic to
  delay heartbeat, lifecycle, and cancellation processing.

**Consequences**

- Transfer overload is explicit and retryable, and the process can calculate an upper
  resource bound independent of complete file size.
- Admission counters and releases require atomic, idempotent store operations and stale
  lease reclamation.
- Conservative defaults can reduce throughput and require tuning from observed metrics.
- Sustained transfer demand can move to a separate deployment through D1 without changing
  the Runner transfer RPC or admission contract.

### transfer-260725/ADR-D9: Use one coordinated protocol cutover without backward compatibility

**Affected requirements:** `transfer-260725/REQ-1`, `REQ-2`, `REQ-3`, `REQ-6`,
`REQ-7`, `REQ-8`, `REQ-9`

Runtime Control, Runtime Runner, and adopted complete-file transfer consumers move to the
new protocol as one coordinated deployment. The current single-user deployment does not
require mixed-version availability, an old-Runner compatibility window, or a legacy
inline-binary fallback.

Implementation assigns a new Runner protocol version that is strictly newer than the
current `2026-07-20` contract. Runtime Control accepts only the new supported Runner
protocol generation for this cutover. Runner registration also requires the explicit
`file.transfer.v1` capability, which declares support for both D6 transfer directions.
A missing protocol version or capability is a registration error rather than a
feature-local fallback condition.

Existing Runtime instances are restarted or recreated with the new Runner before
complete-file operations resume. Runtime Control and Runner may be temporarily
unavailable during the coordinated deployment. Consumers switch directly from the
legacy complete-file path to the new transfer service after the compatible Control and
Runner are running.

The existing `file.upload` and `file.download` capability names and inline operation
aliases are not treated as evidence of the new transfer contract. Adopted consumers do
not call them as a fallback. Ordinary bounded filesystem operations such as `file.read`
and `file.write` remain available under their existing tool semantics and are not
reclassified as complete-file transfer.

Runtime Control still validates both protocol version and capability rather than
assuming that one implies the other. A Runner that advertises `file.transfer.v1` without
implementing the RPC contract is rejected as a protocol violation.

**Rejected alternatives**

- Capability-gated mixed-version routing would preserve old Runner connections and
  require phased Control, Runner, and consumer rollout logic that the current deployment
  does not need.
- Rejecting transfer locally while preserving other operations on an old Runner retains
  an unsupported protocol combination and complicates diagnosis.
- Falling back to inline `file.upload` or `file.download` recreates the original
  message-size failure and contradicts the confirmed no-fallback boundary.

**Consequences**

- Deployment and implementation omit compatibility adapters, dual routing, feature
  gates, and old Runner transfer tests.
- The cutover may briefly interrupt the single user's Runtime operations.
- Protocol mismatches fail during Runner registration instead of later during a file
  transfer.
- Future compatibility requirements must be introduced by a new Requirements snapshot
  rather than retrofitted into this accepted cutover.

### transfer-260725/ADR-D10: Keep transfer-state authority inside Runtime Control and expose an authenticated internal coordinator contract

**Affected requirements:** `transfer-260725/REQ-3`, `REQ-4`, `REQ-6`, `REQ-7`,
`REQ-8`, `REQ-9`, `REQ-11`, `REQ-12`

Runtime Control is the sole process owner of `RuntimeTransferStateStore`. Trusted Server
and Worker feature services do not instantiate or access that store directly. They call a
versioned internal transfer-coordinator RPC terminated by Runtime Control for admission,
attempt preparation, ready/dispatch, cancellation, verified-object handoff, consumer
claim and acknowledgement, terminal settlement, and bounded cleanup status.

The internal coordinator contract carries bounded metadata and opaque trusted-service
handles only. It carries no complete file body and is separate from the external
Runner-facing transfer service. Trusted feature services may use an admitted opaque
object handle with their existing internal S3 authority to perform bounded provider
streaming or object-store-native copy, but the handle never crosses to Runner, model,
public API, or user-visible events.

Every coordinator RPC authenticates a trusted Azents service caller through the existing
Runtime Control TLS boundary and a short-lived service credential rooted in the existing
trusted credential authority. It authorizes the caller's operation, Runtime, Session,
Agent, direction, attempt, and allowed transition before accessing transfer state. A
Runner credential cannot call this service, and a trusted-service credential cannot call
the Runner data RPC as a Runner.

The existing `RuntimeCoordinationStore` remains Redis-backed in the current architecture.
API/Worker and Runtime Control are separate processes and use it for the current Runner
connection registry, request/reply streams, operation metadata, and cancellation. A
process-local Coordination Store would split those authorities and break ordinary Runner
communication.

The transfer-state backend is selected independently:

- `memory` keeps all transfer records inside one Runtime Control process and is valid
  only when every coordinator and Runner transfer RPC reaches that one owner; and
- `redis` shares transfer state across multiple Runtime Control replicas.

When Redis transfer state is selected, it may share a Redis client lifecycle with Runtime
Coordination while retaining a separate interface and key namespace. Selecting memory
for transfer state does not change Runtime Coordination's existing Redis requirement.

**Rejected alternatives**

- Letting Server or Worker processes instantiate the in-memory transfer store creates
  separate state authorities and makes Runtime Control unable to validate or settle the
  same attempt.
- Applying one `memory|redis` selector to both Coordination and Transfer State breaks the
  existing cross-process Runner operation path even with one Runtime Control replica.
- Requiring Redis commands or streams for every transfer-state operation would make the
  transfer capability's standalone state implementation nominal rather than real.
- Adding a relational transfer entity retains short-lived transport state as durable
  product data and reintroduces the authority and lifecycle problems rejected by D4.

**Consequences**

- The memory transfer backend is feasible in the existing multi-process application
  because one Runtime Control process remains the only state owner.
- Phase implementation must add an internal coordinator protobuf/service/client and
  trusted service authentication in addition to the external Runner transfer service.
- Feature services retain authorization and object/provider work, while Runtime Control
  serializes every transfer-state transition.
- Existing Runtime Coordination composition and Redis-backed cross-process behavior stay
  unchanged.
