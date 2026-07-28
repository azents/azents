---
title: "Runtime File Transfer phase 8: External Channel outbound"
created: 2026-07-26
tags: [runtime, files, transfer, external-channel, slack, backend]
---

# Runtime File Transfer phase 8: External Channel outbound

## Phase Execution Plan

- Phase: `8 — External Channel outbound`
- Branch/base: `feature/runtime-file-transfer-08-external-channel-outbound` → `feature/runtime-file-transfer-07-managed-publication`
- PR boundary: Replace the adopted Runtime-source Slack reply relay with one Runtime upload attempt per selected source, a trusted bounded provider-native stream, and a completion-scoped batch consumer boundary. Preserve the existing durable External Channel action and one-attempt provider-delivery contract.
- Inputs: Confirmed `transfer-260725/REQ`; accepted `transfer-260725/ADR`; approved `transfer-260725/DESIGN`; current External Channel delivery specification; `docs/azents/plans/runtime-file-transfer-implementation-plan.md`; completed Phase 3 transfer state, Phase 4 coordinator protocol, Phase 5 Runner upload, Phase 6 source consumers, and Phase 7 managed-object publication contracts; Phase 8 implementer and reviewer discovery baselines.
- Deliverables: Runtime-source preflight and transfer admission through the External Channel delivery path; a trusted batch Runtime-to-provider consumer service; renewable consumer claims; bounded verified-object streaming to Slack; one Slack completion boundary; durable provider-completed and transfer-settlement evidence; exact cancellation, failure, ambiguity, expiry, and cleanup behavior; removal of adopted repeated ordinary Runtime file reads; focused large-file evidence.
- Non-goals: Exchange, Artifact, ModelFile, or FilePart publication; inbound Slack changes; attachment discovery, locator authorization, provider scope, provider-native protocol, or provider size-policy changes; generic provider retry; delivery/provider environment activation; Runtime Control endpoint, credential, TLS, Helm, deployment, autoscaling, or reconciliation rollout wiring; Runner protobuf/data-RPC changes; gRPC message-limit changes; protected Runtime destination replacement; ordinary `file.read`, `file.write`, edit, patch, or text-tool changes; a relational transfer entity; backward compatibility or inline-binary fallback; living-spec promotion.
- Interfaces: The contracts below are fixed before implementation. Private helper names may vary, but the provider-mutation boundary, batch acknowledgement boundary, authority lock boundary, opaque-handle boundary, and cancellation behavior must remain unchanged.

### Interface contract: durable delivery and authority admission

The existing `ExternalChannelActionService` remains the owner of the canonical action,
work mutation, ordered source manifests, delivery intent, provider credentials, and
provider result. It continues to commit an External Channel action and its delivery
intent before provider work begins. It does not persist transfer object handles, object
keys, bucket names, byte chunks, private provider URLs, provider credentials, or Runner
credentials.

For a claimed `REPLY` delivery containing Runtime sources, the delivery worker obtains
the current binding, connection capability, Agent/Session authority, Runtime target and
desired generation under the same transaction and lock boundary that starts the delivery
attempt. That boundary must establish all of the following before the first Runtime
upload admission:

1. the delivery is the exact pending delivery that became `attempting`;
2. the binding and connection remain eligible for outbound upload;
3. every Runtime source still belongs to the admitted action and has its preflight
   regular-file metadata, filename, media type, exact size, per-file limit, and
   aggregate limit;
4. the action's Agent, Session, Runtime, desired generation, and deadline are current;
   and
5. no cancellation, disconnect, action replacement, or source-expiry observation has
   already made the delivery ineligible.

The worker revalidates the current authority immediately before each transfer admission
and before starting provider work. A failed revalidation completes the delivery through
the existing confirmed failure contract without opening a Runtime upload, provider
request, or ordinary Runtime file read.

The lock/transaction is released before waiting on Runtime Control, S3, or Slack. Long
I/O never occurs under a database transaction. A later lifecycle transition may request
cancellation through the existing delivery/transfer cancellation paths; it cannot turn a
known provider success into a failed provider result.

### Interface contract: batch Runtime-to-provider consumer

Add a backend-only External Channel companion to
`RuntimeToServerTransferService`. It is the sole adopted Runtime-source path for
External Channel outbound delivery. It accepts:

- the trusted Runtime ID and current desired Runner generation;
- one ordered Runtime-source descriptor for each already-authorized action manifest;
- Agent, Session, Run/action/delivery correlation, External Channel binding
  correlation, and a stable delivery-batch identity;
- exact preflight size, media type, filename, per-file and aggregate limits;
- authoritative delivery/source expiry and an absolute operation deadline; and
- a provider-stream callback that accepts only a trusted bounded verified-object reader
  and returns provider-local upload evidence.

For every source, the service performs the existing Runtime-to-server metadata preflight,
atomically admits one upload attempt, dispatches one typed Runtime upload intent, waits
for the exact verified object, claims one consumer, and renews every live consumer lease
until the batch is terminal. It uses only the typed
`GrpcRuntimeTransferCoordinatorClient`; External Channel services do not access Transfer
State, Runtime Coordination, transfer object keys, or object-store clients directly.

The provider-stream callback receives one trusted-process-only reader at a time. The
reader exposes exact verified size, media type, filename, bounded chunk iteration, and
explicit close semantics. Its opaque verified-object handle remains inside trusted
backend code and never appears in a Runner RPC, External Channel action payload,
delivery row, provider request value, logs, tool result, model context, public API, or
Redis. The service applies backpressure from the provider write to the object iterator
and retains no complete file body.

The batch service has separate closed operations for:

1. `prepare` — admit, upload, verify, claim, and begin lease renewal for every ordered
   source without provider mutation;
2. `stream` — pass each verified object once to the provider adapter while preserving
   all batch claims;
3. `provider_completed` — record bounded durable provider-success evidence for the
   exact delivery and ordered source attempt/claim correlations before acknowledgement;
4. `acknowledge_and_settle` — acknowledge and settle all claimed consumers after the
   provider completion record exists; and
5. `abandon_or_cancel` — stop reads and abandon/cancel every exact live pre-provider
   claim and upload attempt.

The persisted recovery correlation contains only bounded transfer ID, attempt ID,
consumer-claim ID, revision/phase evidence, delivery-batch identity, and provider
completion state. It never contains an opaque storage handle. It is sufficient for a
trusted recovery worker to retry acknowledgement or query settlement after a confirmed
provider completion without issuing another provider request.

No individual source becomes consumed merely because its file upload stream returned
successfully. The service cannot acknowledge, settle, or release a batch claim as
successful until the one provider completion call for the ordered file set returns
confirmed success.

### Interface contract: Slack provider stream and completion

Slack delivery preserves the current ordered file-manifest and direct external-upload
protocol:

1. obtain one `files.getUploadURLExternal` target for each ordered manifest;
2. stream the corresponding verified Runtime object to that target in bounded chunks;
3. require the provider-streamed byte count to equal the preflight and verified size;
4. retain the returned provider file IDs in manifest order; and
5. invoke `files.completeUploadExternal` exactly once after every upload stream has
   succeeded.

The adapter does not call ordinary Runtime `read_range`, `file.read`,
`FileStorage.get()`, or any complete-body Runtime operation in this adopted path.
It does not build a `bytes` or `bytearray` proportional to a source file. Provider
HTTP request ownership, response closure, cancellation, timeouts, and bounded stream
buffering remain within the provider adapter.

`files.completeUploadExternal` is the provider completion boundary for the whole file
batch. A confirmed completion result causes the delivery worker to durably record
provider completion before it starts consumer acknowledgement. It then returns the
existing delivered result only after its durable provider result is committed. Transfer
acknowledgement/settlement may continue as a recovery-safe cleanup operation when its
transport outcome is uncertain; it does not cause Slack completion to run again.

The provider receives only its existing filename, media type, declared/content length,
ordered upload ID, conversational text, channel, and root-thread values. It receives no
transfer IDs, consumer claims, object handles, keys, bucket names, URLs from internal
storage, credentials, or topology.

### Interface contract: retry, failure, ambiguity, and retention

Provider mutation is at most once for one durable delivery attempt. The existing
External Channel delivery state remains authoritative:

- Preparation failures before any provider request abandon or cancel exact Runtime
  attempts and claims, release admission, and finish through the existing confirmed
  failure/cancellation classification.
- A confirmed provider rejection finishes `failed`; all unacknowledged batch consumers
  are abandoned or cancelled and their transfer objects are eligible for normal cleanup.
- Cancellation before provider mutation stops preparation and abandons/cancels the
  batch. Cancellation during a provider request produces the existing conservative
  `unknown` provider outcome unless Slack has already supplied confirmed completion.
- A timeout, disconnect, cancellation, or ambiguous result after a provider request has
  begun produces `unknown`. The worker never replays any Slack upload or completion
  request. It preserves unacknowledged claims only while their logical expiry permits
  trusted status inspection or reconciliation, then relies on the normal expiry and
  cleanup path.
- A confirmed provider completion is durable before consumer acknowledgement. An
  acknowledgement or settlement transport failure is retried or status-confirmed only
  for the exact recorded claims; it cannot repeat provider mutation or create another
  Runtime upload attempt.
- Logical expiry, claim loss, Runtime generation replacement, source mutation,
  size/integrity mismatch, or authority loss before provider completion prevents
  provider success. A provider result already confirmed before later cleanup failure
  remains a delivered provider result; cleanup evidence remains visible.

An expired, abandoned, consumed, superseded, or terminal transfer attempt is never
revived. Retrying a delivery after its durable provider delivery is `unknown`, `failed`,
or expired follows the existing External Channel action/reconciliation policy and creates
new transfer attempts only if a new provider delivery attempt is expressly authorized.

### Interface contract: cancellation, deadlines, and observability

Every transfer admission, Runtime upload, verified-object claim renewal, object read,
provider HTTP upload, Slack completion request, acknowledgement, settlement, and cleanup
operation uses the earlier of the delivery deadline and the transfer logical expiry.
Lease renewal runs on a bounded cadence for every prepared source and stops immediately
after batch abandonment, cancellation, acknowledgement, terminal settlement, or expiry.

Cancellation closes the active provider request/body stream, stops Runtime transfer
waiting, requests exact cancellation or abandonment, and releases admission through
coordinator authority. `CancelledError` propagates after cancellation is requested; it
does not report a provider success without durable completion evidence. Cleanup failure
records bounded retryable evidence and cannot change a confirmed provider delivery into
a failure.

Logs and metrics include only bounded action, delivery, batch, transfer/attempt, claim,
provider operation, source category, byte-count, phase, outcome, and failure-class
correlations. They exclude file bytes, source paths beyond existing approved diagnostics,
object handles, object keys, buckets, internal URLs, provider credentials, bearer
headers, and tokens.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Delivery authority and durable batch evidence | `/root/runtime-transfer-implementer` | `services/external_channel/{channel_action,file_transfer,event_processor}.py`, persistence helpers/tests only when narrowly required | Current External Channel action/delivery contract; Phase 6/7 transfer clients | Locked start boundary, provider-completion evidence, exact recovery correlation | Action/lifecycle/authority transaction tests; no I/O under transaction |
| Runtime-to-provider batch consumer | `/root/runtime-transfer-implementer` | focused modules under `runtime/transfer/` and tests; coordinator/client only if a narrow existing consumer operation is insufficient | Phase 4 coordinator; Phase 5 upload; Phase 7 renewable claims | Ordered prepare/claim/renew/stream/ack/settle batch service | Memory/Redis parity where contract changes; claim, expiry, cancellation, and recovery tests |
| Slack bounded outbound adapter | `/root/runtime-transfer-implementer` | `services/external_channel/slack_events.py`, provider/file-transfer tests | Batch consumer verified-object reader | One bounded stream per source, one completion per ordered batch, no Runtime control reads | Provider request spies; chunk/backpressure/closure tests; >4 MiB evidence |
| Integration and regression coverage | `/root/runtime-transfer-implementer` | focused External Channel, Runtime transfer, and lifecycle tests | All Phase 8 workstreams | Authority, at-most-once, batch boundary, uncertainty, and no-product-side-effect coverage | Focused backend quality/test commands and diff guard |
| Independent review and final verification | `/root/runtime-transfer-reviewer`, then `/root` | Read-only cumulative Phase 8 diff; root owns final PR verification/shipping | Implementation owner validation complete | Findings/recheck and root scope validation | Provider mutation, batch lease, authority, bounded-stream, no-leak, and non-goal audit |

- Integration order: (1) add the durable delivery completion/recovery correlation and
  locked start/revalidation seam; (2) introduce the batch Runtime-to-provider consumer
  primitive with claim renewal and exact terminal operations; (3) migrate Slack Runtime
  sources to its bounded verified-object stream; (4) record provider completion before
  batch acknowledgement and recovery; (5) remove adopted repeated ordinary Runtime read
  relay; (6) add focused regression coverage and run validation; (7) implementation
  owner requests independent review, fixes accepted Critical/Warning findings, reruns
  validation, and requests the same reviewer recheck.
- Independent review: The implementation owner requests review directly from
  `/root/runtime-transfer-reviewer`. Review criteria: current authority and capability
  are locked/revalidated before upload admission; no transfer/provider work under a DB
  transaction; one Runtime upload attempt per source; no ordinary Runtime complete-file
  relay; bounded streaming and closure; no opaque-handle/data/secret leak; all claims
  survive until one Slack completion; provider completion precedes acknowledgement;
  provider mutation cannot replay; confirmed/ambiguous/cancelled outcomes preserve
  External Channel semantics; claims/cleanup cannot reverse provider success; and no
  Phase 7 or 9 behavior is pulled forward.
- Final validation:
  - `cd python/apps/azents && uv run ruff check . && uv run ruff format --check . && uv run pyright .`
  - `cd python/apps/azents && uv run pytest -vv src/azents/services/external_channel src/azents/runtime/transfer`
  - Focused External Channel action, Slack adapter, Runtime transfer, and lifecycle
    tests selected by changed paths, including the real/fake provider boundary already
    used by the suite.
  - `git diff --check feature/runtime-file-transfer-07-managed-publication..HEAD`
  - pre-commit on every changed file before commit.
- Scope-drift check: Reject Exchange/Artifact/ModelFile/FilePart publication,
  `present_file` changes beyond shared narrow consumer extraction, inbound Slack or file
  discovery changes, new provider protocol/size policy, generic provider retry,
  deployment/provider/Helm wiring, Runner-facing protocol changes, gRPC limit changes,
  database transfer entities, object-handle persistence, bytes in coordinator/Redis or
  delivery rows, ordinary complete-file Runtime fallback, compatibility routing,
  protected overwrite rollout, living-spec promotion, and unrelated refactors.

## Required evidence before independent review

- A Runtime source larger than 4 MiB reaches Slack through exactly one typed Runtime
  upload attempt and bounded provider-native chunks. The adopted path performs no
  ordinary Runtime `read_range`, `file.read`, `FileStorage.get()`, complete control
  event, or whole-body application relay.
- Runtime-source preflight and current lifecycle/capability revalidation share the
  delivery-start lock boundary. Authority, binding, connection, source, or generation
  loss rejects before Runtime upload admission or provider mutation.
- A multi-file reply holds every consumer claim renewed until one successful
  `files.completeUploadExternal`. A successful earlier file stream followed by later
  upload/completion failure leaves no earlier source acknowledged as consumed.
- Provider completion writes durable exact batch/claim recovery evidence before
  acknowledgement. An acknowledgement or settlement transport interruption is recovered
  by exact status/acknowledgement work without another Slack upload or completion call.
- Confirmed provider rejection abandons/cancels all exact live consumers and releases
  admission. Cancellation, timeout, or transport ambiguity after provider work begins
  records `unknown` and proves that the provider mutation is never replayed.
- Provider stream cancellation, early exit, provider error, claim loss, expiry, and
  generation replacement close readers and HTTP resources, stop lease renewal, retain
  no whole-file buffer, and leave cleanup/terminal evidence bounded.
- No Exchange, Artifact, ModelFile, FilePart, public API value, model-visible value,
  Runner message, coordinator/Redis record, provider request, or log exposes an internal
  object handle/key/bucket/URL/credential or complete source bytes.
