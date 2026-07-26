---
title: "Runtime File Transfer phase 6: Server-to-Runtime consumers"
created: 2026-07-26
tags: [runtime, files, transfer, backend, external-channel, engine]
---

# Runtime File Transfer phase 6: Server-to-Runtime consumers

## Phase Execution Plan

- Phase: `6 — Server-to-Runtime consumers`
- Branch/base: `feature/runtime-file-transfer-06-server-to-runtime-consumers` → `feature/runtime-file-transfer-05-runner`
- PR boundary: Migrate every adopted complete-file source that materializes content into a Runtime to the common transfer coordinator and immutable transfer-object path. Preserve feature authorization and destination behavior while removing complete-body relay through ordinary Runner Control operations.
- Inputs: Confirmed `transfer-260725/REQ`; accepted `transfer-260725/ADR`; approved `transfer-260725/DESIGN`; `docs/azents/plans/runtime-file-transfer-implementation-plan.md`; completed Phase 3 storage/state, Phase 4 coordinator/protocol, and Phase 5 Runner transfer contracts; Phase 6 implementer discovery and independent reviewer baseline.
- Deliverables: A trusted Server-to-Runtime transfer service; metadata-only authorized source resolution for Exchange and Artifact; incremental current-run VFS staging; bounded Slack/provider source streaming; durable PREPARING-phase source-cleanup evidence; verified READY-before-dispatch ordering; migrated `import_file` and explicit External Channel inbound consumers; cancellation, cleanup, and exact failure mapping; focused files-above-4-MiB evidence for Exchange, Artifact, and provider sources while VFS remains at its existing 2 MiB product limit.
- Non-goals: Runtime-to-server transfer consumers; `present_file`; Exchange or Artifact publication from a verified Runtime object; External Channel outbound delivery; provider lifecycle command/environment propagation; Runner-facing protobuf or data-RPC changes; provider, Helm, or deployment cutover configuration; protected existing-destination replacement; ordinary `file.write`, edit, patch, read, or text operations; new public API or retained product-file identity; living-spec promotion; backward-compatible or inline-binary fallback. Phase 6 may narrowly extend the trusted coordinator protobuf and Transfer State only for bounded source-preparation cleanup authority discovered during implementation feasibility.
- Interfaces: The contracts below are fixed before implementation. Private helper names may vary, but source authority, admission order, byte boundaries, cleanup ownership, and result semantics must remain unchanged.

### Interface contract: trusted Server-to-Runtime service

Add one backend-only complete-file service separate from `FileStorage`. It accepts:

- an authorized source descriptor;
- the current Runtime ID and desired Runner generation;
- the initiating Agent, Session, Run, and operation correlation;
- the absolute Runtime destination path and overwrite policy;
- the exact expected source size and optional trusted SHA-256;
- applicable product/provider maximum sizes;
- the authoritative source expiration, when present; and
- an absolute operation deadline.

The service returns only after the coordinator reports authoritative terminal success for
the exact attempt. A READY or ENQUEUED status alone is not a successful feature result.
The service uses the typed `GrpcRuntimeTransferCoordinatorClient` contract and never
accesses Transfer State or Runtime Coordination directly.

The implementation uses an injected coordinator client, trusted S3 service, workspace
bucket, transfer prefix, clock, ID source, and bounded transfer settings. Phase 6 defines
and tests the application composition seam. Phase 9 owns endpoint, credential, TLS,
environment, provider, Helm, and deployment activation.

The exact execution order is:

1. validate feature authority, source metadata, destination syntax, overwrite intent,
   Runtime identity/generation, deadline, and configured size limits;
2. atomically admit the metadata-only transfer before opening a provider body, allocating
   an object, starting a copy/multipart operation, or dispatching a Runner intent;
3. resolve the admitted opaque handle to a trusted-process-only transfer object identity;
4. prepare and verify the immutable transfer snapshot through the source-specific path;
5. revalidate feature authority and authoritative source expiry after preparation;
6. mark the exact attempt READY with exact size and SHA-256;
7. dispatch one stable metadata-only Runner intent;
8. observe the exact attempt until terminal success or a concrete transfer failure; and
9. map the outcome through the owning feature's existing user-visible result contract.

Any failure before terminal Runtime commit cancels or settles the exact attempt, releases
admission through coordinator authority, and performs best-effort cleanup without
deleting an earlier valid Runtime destination. Coroutine cancellation is handled
separately from ordinary exceptions and propagates a caller cancellation to the
coordinator before it is re-raised. Cleanup failure records bounded retryable evidence
when the current coordinator contract can represent it; it never exposes an object key,
provider URL, credential, file body, or storage topology in a result or log.

The service never increases a gRPC message limit and never calls `FileStorage.put()` or
ordinary Runner `write_file()` for complete-file delivery.

### Interface contract: durable source-preparation cleanup

The trusted coordinator and Transfer State gain one narrow PREPARING-phase cleanup
contract. This is not a Runner-facing protocol and carries no body, provider credential,
private URL, bucket, object key, or presigned authority.

The state record stores bounded optional preparation evidence:

- one opaque preparation object handle derived from the admitted attempt;
- one opaque multipart upload cleanup handle while multipart work is incomplete; and
- whether a completed preparation object requires deletion.

The trusted coordinator client exposes explicit revision-fenced operations equivalent to:

1. register the opaque preparation object and multipart cleanup handle immediately after
   multipart creation and before uploading the first part;
2. transition the evidence from multipart-abort responsibility to completed-object-delete
   responsibility after successful multipart completion;
3. clear the evidence only after exact owned cleanup succeeds; and
4. read the resulting bounded transfer status.

The protobuf uses an explicit closed preparation-cleanup state rather than overloading the
existing terminal cleanup status. Generated Python modules and the typed shared client are
regenerated and committed.

State rules:

- registration is valid only for the exact current PREPARING download attempt, live
  admission lease, expected revision, Runtime identity, desired generation, and
  unexpired deadline;
- duplicate registration is idempotent only for the exact same handles and state;
- conflicting handles, stale attempts, cancellation, expiry, terminal state, and READY
  reject mutation;
- READY requires no outstanding preparation multipart or completed-object cleanup
  responsibility;
- cancellation, expiry, supersession, and reconciliation retain the cleanup evidence
  until abort/delete succeeds;
- cleanup completion never changes a successful or failed feature result and cannot
  mutate a newer attempt; and
- in-memory and Redis implementations pass the same contract tests.

Runtime Control's cleanup collaborator resolves only the opaque preparation handle within
the configured transfer prefix and uses exact stored evidence to abort the multipart
upload or delete the completed preparation object. Worker remains the normal cleanup
executor and records each transition through the coordinator. Runtime Control becomes the
recovery executor when Worker disappears; Transfer State remains the sole cleanup
authority in both cases.

### Interface contract: authorized sources

Replace `ImportResolvedFile.body` with a closed typed source union whose shared metadata
contains:

- canonical source URI;
- source kind;
- display filename and media type;
- exact size;
- optional trusted SHA-256;
- authoritative source expiration when present; and
- a trusted-process-only source capability.

Supported source variants are:

- **managed object** — an authorized workspace S3 object identity for Exchange or
  Artifact, with trusted size, SHA-256, and source expiry;
- **current-run VFS** — one authorized canonical VFS entry whose Base64 representation,
  declared size, and SHA-256 are incrementally decoded and checked by the preparation
  path; and
- **provider stream** — a deferred async source opener that is invoked only after
  admission and owns closure of provider response resources on completion, early exit,
  cancellation, and error.

The union and all logs/results remain backend-only. Object keys and private provider URLs
are never placed in model-visible output, Runner messages, coordinator messages, Redis,
or public API values.

### Interface contract: Exchange and Artifact resolution

Exchange and Artifact gain metadata-only internal authority resolution methods for
Runtime import. Existing public download and bounded product paths remain unchanged.

The internal resolver must:

- validate the canonical `SessionResourceAuthority`;
- preserve Agent, Workspace, Session/root-retention, Run, and source-status checks;
- reject expired or unavailable metadata before transfer admission;
- return the trusted source object identity, exact size, persisted SHA-256, media type,
  filename, and expiration without calling `download_bytes()`; and
- support a second authority/source-validity check after snapshot preparation and before
  READY/dispatch.

The managed-object preparation path uses S3-native immutable copy into the admitted
transfer namespace. It verifies source size, source identity evidence, destination size,
and transfer-owned SHA-256 metadata. It never downloads and re-uploads unchanged bytes
through application memory.

### Interface contract: current-run VFS staging

The VFS import path consumes the already-authorized canonical projection without calling
`entry.decode_body()` for complete-file import.

Its decoder:

- processes the existing Base64 string in bounded, quartet-aligned input slices;
- uses strict Base64 validation and rejects malformed padding or trailing data;
- incrementally computes actual decoded size and SHA-256;
- never creates a second complete binary `bytes` or `bytearray`;
- rejects actual-size or digest mismatch before READY; and
- closes/aborts S3 work on cancellation or decode failure.

Because VFS metadata already carries a trusted SHA-256, the final immutable transfer
object may be created directly with that digest, provided exact persisted size and hash
are verified before READY.

### Interface contract: provider streaming preparation

`SlackConversationClient` exposes a deferred, resource-owning bounded byte stream rather
than returning one complete `bytes` value for the adopted inbound transfer path.

The provider path preserves:

- active AgentSession/binding lookup and exact provider match;
- `download_files` capability and credential availability;
- credential decryption only in trusted server code;
- current provider metadata and provider file-ID equality;
- supported file mode and filename requirements;
- allowlisted server-only private URL validation;
- configured declared-size limit and exact declared/actual size equality; and
- existing bounded provider failure classifications.

Admission completes before the private body stream opens. The stream applies
backpressure, enforces actual bytes against both the declared size and configured maximum,
and closes the HTTP response when the consumer exits.

When a provider does not supply SHA-256 before streaming, use an attempt-owned
preparatory multipart object whose key and upload handle remain trusted implementation
details. Stream bounded parts while computing size and SHA-256, complete the preparatory
object, promote it through an S3-native immutable copy to the admitted canonical transfer
object with final transfer metadata, verify the canonical object, then delete the
preparatory object. The preparatory object is never marked READY or exposed as a transfer
snapshot.

Cleanup execution is coordinated through the durable source-preparation cleanup contract:

- Worker registers the opaque preparation handle and multipart upload handle immediately
  after creation and before the first part;
- Worker normally performs abort/delete and records the exact transition;
- Runtime Control reconciliation performs the same exact cleanup if Worker disappears;
- the multipart-creation-to-registration window is the only unavoidable process-loss
  gap, matching the existing Runner-upload pattern; an orphan in that window is
  inaccessible, deterministically prefixed, and handled by Phase 9 bounded prefix
  reconciliation and storage lifecycle; and
- object existence never authorizes READY, dispatch, or later access.

If the shared S3 library requires an additional preparation primitive, add the narrowest
bounded API and tests in `az-common`; do not weaken the verified transfer-object contract
or reintroduce eager body reads.

### Interface contract: adopted consumers

`import_file` preserves:

- `exchange://`, `artifact://`, and current-run `azents://` support;
- default `/tmp/agent/imports/<filename>` behavior;
- filename sanitization;
- default-path deduplication;
- absolute-path validation;
- explicit no-overwrite preflight error;
- destination read-only/path error mapping;
- feature authority revalidation;
- exact source kind, media type, and size in success text; and
- the temporary-path durability warning.

The preflight existence check is advisory. Runner publication remains authoritative for
destination races. Phase 6 forwards `overwrite=true`, but existing-destination replacement
continues to fail closed under the Phase 5 boundary until Phase 9 supplies protected
same-filesystem staging. No pathname-based or ordinary `write_file()` fallback is allowed.

External Channel inbound preserves its current locator, binding, capability, credential,
metadata, size, filename, destination, and error contracts while replacing
`download_private_file() -> bytes -> FileStorage.put()` with the common transfer service.
The tool still requires explicit Agent selection of one locator and an absolute Runtime
destination.

The shared Runtime instruction context may carry a backend-only transfer target/service
capability in addition to ordinary `FileStorage`. That capability contains Runtime
identity and generation metadata only; it does not contain file bytes, S3 credentials,
object keys, private URLs, or Runner credentials.

### Interface contract: retries, cancellation, and failure

- One invocation owns one transfer ID, attempt ID, lease ID, and stable dispatch ID.
- A retry from byte zero creates a new attempt and cannot revive a prior object or
  destination.
- Source preparation never dispatches while PREPARING and marks READY exactly once.
- Authority loss, source expiry, source change, size/hash mismatch, provider failure,
  S3 failure, cancellation, deadline, generation replacement, dispatch rejection, and
  Runner destination failure produce a concrete failed/cancelled result rather than a
  later generic timeout.
- Polling or awaiting terminal state is bounded by the earlier of the operation deadline
  and logical transfer expiry.
- Cancellation after Runner destination commit cannot reverse committed success; the
  Phase 5 commit-authority semantics remain authoritative.
- Logs contain bounded IDs, source category, phase, byte counts, and failure class, but
  no file content or secret-bearing location.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Trusted preparation cleanup state and coordinator contract | `/root/runtime-transfer-implementer` | `proto/azents/runtime_control/v1/runtime_transfer_coordinator.proto`; generated/typed coordinator client under `python/libs/azents-runtime-control/`; focused `python/apps/azents/src/azents/runtime/transfer/` state, cleanup, coordinator server, and tests | Phase 3 state and Phase 4 trusted coordinator | PREPARING-phase opaque cleanup evidence, exact transitions, READY fence, Worker-loss reconciliation, generated artifacts | Runtime-control generator drift check and quality suite; memory/Redis parity; coordinator auth/revision tests; cleanup reconciliation tests |
| Trusted transfer application service and source staging | `/root/runtime-transfer-implementer` | New or focused modules under `python/apps/azents/src/azents/runtime/transfer/`; focused tests; narrow `python/libs/az-common/src/azcommon/infra/s3/` extensions and tests only if required for unknown-digest provider staging | Preparation cleanup contract, Phase 3 S3/state, and Phase 4 coordinator client | Admission-first source preparation, object-native copy, bounded stream/VFS staging, READY/dispatch/terminal orchestration, cancellation and cleanup | Backend and az-common Ruff/format/Pyright; focused unit/integration tests including >4 MiB and cancellation |
| Managed-object and VFS import resolution | `/root/runtime-transfer-implementer` | `python/apps/azents/src/azents/services/exchange_file/`; `services/artifact.py`; `services/vfs.py` or focused VFS helper; `engine/tools/import_resolver.py`; tests in the same areas | Authorized source union and transfer service interface | Metadata-only object sources and incremental VFS source without eager import bodies | Resolver/service tests; eager-download spies; invalid Base64/size/hash/expiry/authority tests |
| `import_file` consumer migration | `/root/runtime-transfer-implementer` | `python/apps/azents/src/azents/engine/tools/import_file.py`; `engine/tools/builtin.py`; `engine/tools/runtime_instruction_context.py`; `worker/deps.py` only for a phase-9-ready injected composition seam; focused tests | Transfer service and source resolution complete | Complete imports use the transfer service while ordinary filesystem tools remain unchanged | Tool and lifecycle regression tests; destination, overwrite, error, success-copy, and >4 MiB assertions |
| External Channel inbound migration | `/root/runtime-transfer-implementer` | `python/apps/azents/src/azents/services/external_channel/file_transfer.py`; `slack_events.py`; `engine/tools/external_channel.py`; focused tests | Provider stream source and transfer service complete | Explicit Slack/provider downloads stage with bounded streaming and common Runner delivery | External Channel service/tool tests; backpressure, cancellation, mismatch, provider error, no-intent-before-READY, and >4 MiB tests |
| Independent review and final verification | `/root/runtime-transfer-reviewer`, then `/root` | Read-only cumulative Phase 6 diff; root owns final verification and shipping metadata | Implementation owner validation complete | Reviewer findings and recheck; root scope/quality verification | Diff/non-goal audit and full phase command matrix |

- Integration order: (1) add and verify durable PREPARING cleanup state/coordinator contracts and regenerate clients; (2) finalize authorized source and transfer-service values; (3) add any required bounded S3 preparatory-stream primitive; (4) implement coordinator orchestration and exact cleanup/error behavior; (5) add metadata-only Exchange/Artifact resolution; (6) add incremental VFS decode/staging; (7) migrate `import_file`; (8) expose deferred Slack byte streaming and migrate External Channel inbound; (9) add composition seam without Phase 9 deployment activation; (10) run complete validation and scope comparison.
- Independent review: The implementation owner requests review directly from `/root/runtime-transfer-reviewer` after its own validation, applies every accepted Critical/Warning finding, reruns affected checks, and requests the same reviewer to recheck. Review criteria: authorization and source-expiry preservation; admission before source/body/object work; exact READY gate; no eager managed-object download or whole-file VFS/provider buffer; bounded provider response ownership and cancellation; immutable copy/promotion and complete cleanup evidence; generation/revision/deadline fencing; destination/overwrite semantics; no bytes/secrets in coordinator/control/Redis/logs; no legacy fallback; no Phase 7-9 behavior.
- Final validation:
  - `cd python/libs/az-common && uv run ruff check . && uv run ruff format --check . && uv run pyright . && uv run pytest -vv` when the shared S3 library changes.
  - `cd python/libs/azents-runtime-control && uv run python scripts/generate_proto.py && git diff --exit-code -- src/azents_runtime_control/proto && uv run ruff check . && uv run ruff format --check . && uv run pyright . && uv run pytest -vv`
  - `cd python/apps/azents && uv run ruff check . && uv run ruff format --check . && uv run pyright .`
  - `cd python/apps/azents && uv run pytest -vv src/azents/runtime/transfer src/azents/engine/tools/import_file_test.py src/azents/engine/tools/import_resolver_test.py src/azents/engine/io/file_resource_lifecycle_verification_test.py src/azents/services/exchange_file/service_test.py src/azents/services/artifact_test.py src/azents/services/vfs_test.py src/azents/services/external_channel/file_transfer_test.py src/azents/engine/tools/external_channel_test.py src/azents/engine/tools/builtin_test.py`
  - Focused real S3/RustFS or faithful integration coverage for managed-object copy and provider preparatory-object promotion when the required fixture is available in this phase; Phase 10 remains the full E2E gate.
  - `git diff --check feature/runtime-file-transfer-05-runner..HEAD`
  - pre-commit on every changed file before commit.
- Scope-drift check: Compare the final diff with this plan and the Phase 6 section of the multi-phase plan. Reject Runtime-to-server upload consumers, `present_file`, final Exchange/Artifact publication, outbound provider delivery, provider lifecycle fields, Runner-facing Runtime Control or data-RPC changes, trusted coordinator changes beyond the bounded preparation-cleanup contract above, Helm/deployment values, protected overwrite staging, living-spec promotion, gRPC message-limit increases, direct Runner S3 access, presigned URLs, body-bearing coordinator/Redis/control messages, ordinary file-operation rewrites, compatibility fallbacks, or unrelated refactors.

## Required evidence before independent review

- Exchange and Artifact import resolution returns metadata/object capability without
  invoking `download_bytes()`, preserves source expiry, and revalidates authority before
  dispatch.
- Managed-object preparation invokes S3-native copy and produces exact size/SHA-256 at
  the Runtime destination for a source larger than 4 MiB.
- VFS import incrementally decodes a source at the existing 2 MiB accepted product
  boundary without calling `decode_body()` or retaining a complete decoded body, and
  rejects malformed Base64, size mismatch, and SHA-256 mismatch before READY. The phase
  does not raise `VFS_FILE_MAX_BYTES`; lower-level decoder tests may use synthetic larger
  chunks only to prove the helper's bounded behavior outside the product acceptance path.
- Slack/provider download opens the private body only after admission, applies
  backpressure, enforces declared and actual limits, closes the response on every exit,
  and transfers a deterministic source larger than 4 MiB without a complete `bytearray`
  or `bytes` relay.
- Admission rejection performs no S3 source copy, multipart creation, provider body open,
  VFS decode, Runner intent, or Runtime destination publication.
- Source preparation failure/cancellation aborts or deletes attempt-owned S3 work,
  releases admission through terminal coordination, dispatches no Runner intent, and
  reports no Runtime success. A simulated Worker loss after cleanup registration leaves
  exact state evidence that Runtime Control reconciliation consumes; stale cleanup cannot
  affect a replacement attempt.
- READY is recorded only after final canonical transfer-object verification, and dispatch
  is attempted only from the exact resulting revision.
- A destination race with `overwrite=false` fails without replacing the winner.
  Existing destination plus `overwrite=true` remains a concrete fail-closed result until
  Phase 9; no unsafe fallback is used.
- Runner generation replacement, deadline, caller cancellation, and stale revision cannot
  turn a failed/superseded attempt into success or affect a newer attempt.
- The default Runner Control message limit remains unchanged, and no coordinator,
  Runtime Coordination, Runner Control, result, log, or test assertion exposes file-body
  content, credentials, private provider URLs, bucket names, object keys, or presigned
  access.
