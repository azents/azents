---
title: "Runtime File Transfer phase 5: Runner transfer client and filesystem safety"
created: 2026-07-26
tags: [runtime, files, transfer, grpc, runner, filesystem, security]
---

# Runtime File Transfer phase 5: Runner transfer client and filesystem safety

## Phase Execution Plan

- Phase: `5 — Runner transfer client and filesystem safety`
- Branch/base: `feature/runtime-file-transfer-05-runner` → `feature/runtime-file-transfer-04-control-protocol`
- PR boundary: Implement the untrusted Runtime Runner side of the Phase 4 transfer protocol, including a physically distinct authenticated data channel, bounded bidirectional streaming, transfer-task correlation, fd-backed unnamed local snapshots, verified same-filesystem destination staging, atomic no-replace publication, and fail-closed existing-destination replacement until Phase 9 supplies the protected staging boundary required for atomic replacement. Do not migrate production feature consumers or add deployment cutover wiring.
- Inputs: Confirmed `transfer-260725/REQ`; accepted `transfer-260725/ADR`; `transfer-260725/DESIGN`; `docs/azents/plans/runtime-file-transfer-implementation-plan.md`; completed Phase 3 storage/state primitives; completed Phase 4 Runner Transfer and Runner Control protocols and Runtime Control services; current Agent Runtime Control and file-storage specs; Phase 5 repository discovery.
- Deliverables: Shared typed Runner Transfer gRPC client; Runner Control transfer intent/cancellation/result handlers; a bounded Runner transfer task manager isolated from ordinary operations; unnamed-fd download staging and atomic no-replace commit; fail-closed existing-destination replacement without an approved protected staging boundary; unnamed-fd upload snapshot and streaming; exact deadline/cancellation/generation/dispatch fencing; atomic Runtime Control settlement of exact download commit evidence; optional transfer endpoint configuration defaulting to the Control endpoint; protocol/capability advertisement; focused filesystem, client, task-manager, state-contract, and real-socket integration tests.
- Non-goals: Server/Worker feature consumer migration; Exchange or Artifact publication; External Channel provider upload/download changes; provider command or environment forwarding; Helm/provider/deployment propagation; enabling existing-destination replacement before Phase 9 provides a workload-inaccessible same-filesystem staging boundary; living-spec promotion; legacy inline-binary fallback; mixed-version compatibility; exposing storage credentials, endpoints, bucket names, object keys, opaque trusted-service handles, or URLs to Runner; raising any gRPC message limit.
- Interfaces: Phase 4 protobufs, `RUNNER_TRANSFER_PROTOCOL_VERSION`, `RUNNER_TRANSFER_CAPABILITY`, `MAX_TRANSFER_CHUNK_BYTES`, identity fields, result combinations, and storage authority remain fixed. Phase 5 may add typed client and Runner-local abstractions and may make the minimal Transfer State/result-settlement correction required to atomically preserve exact download commit evidence across a concurrent deadline/cancellation race. It must not change protocol messages, permit a new byte stream, revive a terminal attempt, or move storage authority into Runner.

## Fixed Runner-side contract

- `AZ_RUNTIME_TRANSFER_ENDPOINT` is optional and defaults to `AZ_RUNTIME_CONTROL_ENDPOINT`. It selects only the Runner Transfer service endpoint.
- Runner Control and Runner Transfer always use separately created `grpc.aio.Channel` instances with local subchannel pools, even when their endpoint and TLS settings are identical. The implementation does not set send/receive message-size options.
- The transfer channel reuses the Runtime-bound Runner bearer credential and the existing TLS or explicit insecure-transport policy. It receives no S3 or provider credential.
- Runner registration advertises exactly the shared `RUNNER_TRANSFER_PROTOCOL_VERSION` and adds the shared `RUNNER_TRANSFER_CAPABILITY` (`file.transfer.v1`). Phase 9 owns coordinated production configuration and strict deployment cutover.
- Transfer tasks have a separate bounded concurrency budget from ordinary Runner operations. Queueing is bounded; inability to accept a task returns a bounded `RESOURCE_EXHAUSTED` result without opening a data RPC or touching a filesystem path.
- Active work is keyed by the exact transfer identity, operation ID, dispatch ID, direction, and accepted Runner generation. An exact duplicate cannot create a second task or second local publication. A conflicting identity or dispatch fails closed.
- A transfer cancellation affects only the matching transfer task. Control disconnect or Runner shutdown cancels active transfer tasks, closes the independent transfer client, and cleans task-owned local files without blocking ordinary-operation cleanup.
- Every blocking boundary before irreversible destination publication uses the earlier of the intent deadline and local task cancellation. Runner rechecks both under the same task-local commit lock immediately before publication.
- Atomic destination publication is the download success linearization point. A cancellation or deadline observed before that point wins and removes only staging state. Once publication succeeds, the committed destination is authoritative and Runner must emit the successful `destination_committed=true` result even if cancellation, deadline, or shutdown is observed immediately afterward; it must never misreport an already committed file as `destination_committed=false`. Runtime Control settlement must preserve this commit-wins ordering for the exact attempt while continuing to reject stale, conflicting, or already terminal evidence.
- Runner reports only the bounded Phase 4 `RunnerTransferResult`. It never reports local temporary paths, free-form exception text, file bytes, storage authority, or provider details.
- Linux does not provide an atomic operation that replaces an existing pathname directly from an unnamed `O_TMPFILE` descriptor. Phase 5 therefore publishes the exact verified descriptor with atomic no-replace semantics. An absent destination may be published for either overwrite policy, but an existing destination with `overwrite=true` fails closed. Phase 9 must provide a genuinely workload-inaccessible same-filesystem Runner staging boundary through UID or mount isolation before enabling atomic replacement. A same-UID writable directory, mutable pathname, or compatibility fallback is not an acceptable substitute.

## Download commit barrier and settlement ordering

Phase 4 moves a download to `VERIFYING` immediately before it emits the completion frame. Phase 5 uses that transition as a bounded commit barrier:

- `begin_verification()` for a download records an immutable `runner_commit_expires_at` equal to verification time plus the configured stream lease (30 seconds under the fixed Phase 4 defaults).
- This is a metadata/result-settlement grace only. It does not extend `deadline_at` or `logical_expires_at`, authorize another byte read, keep a data RPC open, allow an object to be reopened, delay transfer-object cleanup, or permit a new attempt stream.
- After the completion frame, Runner performs its final cancellation/deadline/path fence under one task-local commit lock and then atomically publishes. Cancellation or deadline observed before publication produces no commit. Publication itself is the local success linearization point.
- While an exact current download remains `VERIFYING` and the commit grace has not elapsed, deadline/cancellation is recorded and all byte access remains invalid, but reconciliation does not terminalize the attempt ahead of the bounded Runner commit result.
- The state-store contract adds `confirm_download_commit(...)` rather than a `get()` followed by `mark_committed()` and generic terminal settlement. In one mutation it verifies the exact current transfer/attempt/runtime/desired generation/accepted generation/operation/dispatch/direction, `VERIFYING` phase, stream claim, manifest, revision lineage, and `now < runner_commit_expires_at`.
- `confirm_download_commit(...)` transitions directly to immutable `TERMINAL/SUCCEEDED`, records download commit confirmation, and releases admission authority. It does not return an intermediate `COMMITTED` record to generic `settle_terminal()` where cancellation or elapsed deadline could recanonicalize the result.
- Exact successful `destination_committed=true` evidence within the barrier wins over `CALLER`, `DEADLINE`, or `SHUTDOWN` recorded after verification, including a result received after `deadline_at` or `logical_expires_at`. This narrowly acknowledges a destination already published after Runner's final local fence; it does not permit byte/object access or delay object cleanup.
- `SUPERSEDED`, any desired/accepted generation mismatch, cancellation recorded before verification, a pre-existing terminal state, identity/operation/dispatch/direction/claim/manifest/revision mismatch, and exact `now >= runner_commit_expires_at` always reject success.
- An exact failure or cancelled result settles the recorded cancellation/deadline/failure instead. When the commit grace expires without an accepted result, reconciliation settles once using supersession, recorded cancellation authority, deadline expiry, or bounded stream failure as applicable. A later result cannot revive that terminal attempt.
- Coordinator `cancel()` and `expire()` record and dispatch `CALLER`, `DEADLINE`, or `SHUTDOWN` during an exact live `VERIFYING` grace but defer terminalization to commit confirmation, Runner failure, or grace expiry. Generation replacement/revocation and `SUPERSEDED` never defer and fence immediately.
- Periodic deadline/logical-expiry reconciliation denies byte/object access and may start object cleanup immediately, but defers only terminal result selection for the exact live commit grace. Grace-expiry reconciliation and terminal reply repair remain bounded and idempotent.

The Result Coordinator calls `confirm_download_commit(...)` directly after durable operation correlation, so no intervening expiry/cancellation read can split the commit decision. After atomic terminal success, object cleanup and final reply correlation are idempotent follow-up work; cleanup failure cannot reverse success. Memory, Redis, Result Coordinator, and Terminal Coordinator implementations must pass the same exact race contract.

## Shared client and Control-stream integration

The shared `azents-runtime-control` library adds:

- a typed `GrpcRunnerTransferClient` owning its own channel and authenticated metadata;
- bounded `DownloadTransfer` iteration and `UploadTransfer` request streaming using the generated Phase 4 service;
- domain values for download chunks/completion and authoritative upload results where useful to keep protobuf details out of Runner filesystem code;
- deterministic mapping from gRPC statuses to the closed `RunnerTransferFailure` values;
- transfer intent and cancellation handler registration on `GrpcRunnerControlClient`;
- serialization of `RunnerTransferResult` onto the existing metadata-only Control stream; and
- close behavior that fails or cancels pending transfer delivery without affecting an independently owned data channel.

The Control receiver validates the Phase 4 message through the existing typed mapping before invoking Runner code. Its transfer-intent handler performs only synchronous validation and bounded task admission, then returns without awaiting the data or filesystem task so heartbeat, ordinary operation, and cancellation delivery remain responsive. Unknown enum sentinels, missing required optional-field presence, invalid hashes, invalid identity bounds, incompatible protocol version/capability, or contradictory direction fields close or reject the transfer instruction before filesystem or data-RPC work.

## Download contract: Server to Runtime

For a `DOWNLOAD` intent, Runner:

1. validates protocol/capability, exact generation, required expected size and SHA-256, explicit overwrite policy, runtime path bounds, and deadline;
2. resolves the destination lexically through the existing workspace policy without accepting a symlink in the existing destination or parent chain;
3. validates or creates the destination parent without following a substituted symlink;
4. creates an attempt-owned unnamed regular file on the destination filesystem with `O_TMPFILE` and restrictive permissions, retaining the exact descriptor through verification and publication;
5. opens `DownloadTransfer` with only the Phase 4 transfer identity;
6. accepts only non-empty chunks no larger than `MAX_TRANSFER_CHUNK_BYTES`, beginning at offset zero and exactly matching the next expected offset;
7. writes incrementally without whole-file buffering while computing SHA-256 and exact length;
8. requires exactly one completion frame and no data after completion, and verifies stream completion, intent manifest, locally observed manifest, and completion manifest are identical;
9. flushes and `fsync`s the temporary file before publication;
10. rechecks destination and parent safety immediately before commit; and
11. publishes the exact verified descriptor atomically with no-replace semantics.

Phase 5 publishes with `linkat(..., AT_EMPTY_PATH)` or an equivalent exact-fd no-replace primitive. With `overwrite=false`, a destination present at commit fails explicitly. With `overwrite=true`, an absent destination may publish through the same primitive, but an existing destination fails closed until Phase 9 provides the protected same-filesystem staging boundary needed for atomic replacement. The Runner never creates a workload-mutable named staging path as a fallback. A symlink, non-regular destination, destination race, unsupported existing-destination replacement, cancellation, deadline, missing completion, offset error, oversize, checksum mismatch, stream failure, or local I/O error closes only the attempt-owned descriptor and reports no commit.

A successful result contains the verified size and SHA-256, `destination_committed=true`, and no failure. No success is reported until atomic publication completes.

## Upload contract: Runtime to Server

For an `UPLOAD` intent, Runner:

1. validates protocol/capability, exact generation, expected size, source path bounds, direction fields, and deadline;
2. resolves the source lexically and rejects symlink traversal, a symlink final component, non-regular files, and unreadable files;
3. opens the source without following a substituted final symlink and records file-descriptor and path identity before copying;
4. copies through a fixed bounded buffer into an attempt-owned local snapshot without retaining the complete file in memory, computing SHA-256 and exact size during the copy;
5. checks cancellation/deadline between bounded reads and writes;
6. flushes and `fsync`s the snapshot;
7. rechecks source descriptor and path identity, type, size, modification/change metadata, and the admitted expected size after snapshot creation;
8. fails before opening `UploadTransfer` if the source changed or the snapshot manifest is inconsistent;
9. sends exactly one opening frame, ordered non-empty chunks no larger than `MAX_TRANSFER_CHUNK_BYTES`, and exactly one completion declaration;
10. requires the authoritative Runtime Control result to equal the snapshot size and SHA-256; and
11. removes the local snapshot on success, failure, cancellation, deadline, or shutdown.

A successful result contains the authoritative size and SHA-256 returned by Runtime Control, `destination_committed=false`, and no failure. Runner never receives or infers the transfer object identity. An interrupted nonterminal upload is not resumed; a later attempt starts from byte zero.

## Local task lifecycle and cleanup

- A dedicated Runner transfer manager owns active task admission, task cancellation, bounded completed-result tombstones for exact duplicate delivery within one Control connection, and close ordering.
- Filesystem workers use cooperative cancellation and do not swallow `asyncio.CancelledError`. Async task cancellation is translated to the Phase 4 cancellation outcome only when the exact intent remains current.
- Attempt-owned download staging and upload snapshots remain unnamed descriptors and are never sent over gRPC.
- Normal success/failure/cancellation closes local temporary descriptors synchronously on the task path. Kernel descriptor lifetime reclaims the unnamed inode after process death, so Phase 5 does not use a same-UID mutable orphan journal or pathname cleanup.
- Phase 9 must define bounded cleanup for any protected named staging entry introduced to support atomic replacement. That cleanup must use ownership evidence inaccessible to the workload, protect active attempts, follow no symlink, validate the exact expected regular file, apply the one-hour equality boundary, and never unlink an arbitrary path recovered only from mutable workload metadata.
- Result emission is shielded only long enough to enqueue one bounded Control message. Failure to emit because Control disconnected does not keep a filesystem task or data channel alive.

## Ordered workstreams

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared Runner transfer client and Control handlers | `/root/runtime-transfer-implementer` | `python/libs/azents-runtime-control/src/azents_runtime_control/`, matching library tests; generated protobuf files only if an unexpected protocol defect requires an approved plan change | Phase 4 protocol | Typed data client, status mapping, transfer handler/result support, distinct-channel option | Library Ruff, format, Pyright, Pytest; protobuf drift only if proto changes |
| Runner filesystem primitives and transfer manager | `/root/runtime-transfer-implementer` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/transfer*.py`, workspace helpers when required, matching tests | Shared client contract | Bounded tasks, unnamed-fd download stage/no-replace commit, fail-closed existing-destination replacement, unnamed-fd upload snapshot/stream, cancellation and cleanup | Runner focused race/cancellation/integrity tests, repeated where scheduling-sensitive |
| Runner process wiring and configuration | `/root/runtime-transfer-implementer` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/main.py`, `main_test.py`, package configuration/lock files when required | Client and manager | Separate channels, endpoint default, capability/version advertisement, close ordering, bounded transfer limits | Runner config/startup tests; Ruff, format, Pyright, full Pytest |
| Download commit authority settlement | `/root/runtime-transfer-implementer` | `python/apps/azents/src/azents/runtime/transfer/{data,store,memory,redis,result_coordinator,coordinator}.py`, matching contract/unit tests | Download local commit contract | Bounded `VERIFYING` commit barrier, direct atomic terminal-success mutation, cancel/expire deferral, supersession fencing, and repair semantics shared by memory/Redis | Race tests for commit vs cancellation/deadline/shutdown/supersession/grace expiry, reconciliation, backend parity, terminal immutability, cleanup and reply repair |
| Real-socket integration | `/root/runtime-transfer-implementer` | Existing Runtime Control gRPC integration tests and test-only dependency metadata if needed | All prior workstreams | Production Runner client/filesystem against Phase 4 service, >4 MiB default-limit evidence, channel/control isolation | Focused real gRPC tests with no message-limit overrides; ordinary operation and heartbeat remain live |

One stable implementation owner performs these workstreams in order because their paths and interfaces overlap. `/root` reserves phase-plan updates, final integration verification, commit/PR creation, and stack progression. The implementation owner directly requests review from `/root/runtime-transfer-reviewer`, applies review findings, runs affected validation, and requests recheck before `/root` performs final verification.

## Integration order

1. Add shared typed transfer client values and the independent gRPC data client.
2. Extend the Control client with typed intent/cancel handlers and bounded result emission.
3. Add the bounded download `VERIFYING` commit barrier and direct atomic terminal-success mutation to memory/Redis state, Result Coordinator, and Terminal Coordinator cancellation/expiry/reconciliation paths, with backend-parity race tests.
4. Add unnamed-fd filesystem staging, snapshot, verification, exact-fd no-replace publication, and fail-closed existing-destination replacement primitives with exhaustive unit tests.
5. Add the transfer task manager and connect it to Control delivery and the data client.
6. Wire Runner startup configuration, registration capability/version, separate channel creation, and shutdown ordering.
7. Add real-socket integration against the Phase 4 service, including a file larger than the default 4 MiB message limit and a simultaneous ordinary Runner operation.
8. Run cumulative Phase 5 validation and compare the diff to deliverables and non-goals.

## Independent review

- Owner: `/root/runtime-transfer-reviewer`, which does not edit implementation paths.
- Inputs: Requirements, ADR, Design, multi-phase plan, this phase plan, Phase 4 plan, current specs, exact Phase 4 base SHA, Phase 5 head SHA, and primary-agent validation evidence.
- Scope: Untrusted Runner boundary; absence of storage authority leakage; physically distinct channels; no message-limit options; bounded memory/disk/queue behavior; strict frame ordering and completion; source/destination symlink and substitution races; exact-fd no-overwrite atomicity; fail-closed existing-destination replacement without a protected staging boundary; source mutation detection; exact checksum/size verification; cancellation/deadline/generation/dispatch fencing; duplicate intent behavior; descriptor cleanup; result validity; ordinary Control responsiveness; and Phase 6-9 scope exclusions.
- Output: Grounded Critical/Warning/Suggestion/Consistency findings with exact file and line references, exploit or failure sequence, and required validation. The implementation owner fixes Critical and Warning findings, runs affected validation, and asks the same reviewer to recheck them. `/root` performs final verification only after that cycle completes.

## Final validation

Run from the relevant subproject directories:

```console
cd python/libs/azents-runtime-control
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest

cd python/apps/azents-runtime-runner
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest

cd python/apps/azents
uv run ruff check <changed integration test paths>
uv run ruff format --check <changed integration test paths>
uv run pyright <changed integration test paths>
uv run pytest -q <changed Runtime Control/Runner transfer integration tests>
```

Also run:

- shared Memory/Redis/Coordinator commit-authority parity tests proving: successful publication evidence received after deadline/logical expiry but before grace becomes immutable terminal success while object access remains denied; post-verification `CALLER`, `DEADLINE`, and `SHUTDOWN` races lose to exact commit evidence; `SUPERSEDED`, generation mismatch, pre-verification cancellation, pre-existing terminal state, and exact grace equality reject success; reconciliation before grace defers only terminalization while generation replacement still fences immediately; grace expiry settles once and late evidence cannot revive; object cleanup is not delayed and cleanup failure cannot reverse success; final reply repair remains idempotent;
- focused filesystem tests for symlink parents/final targets, destination-appears races, exact-fd no-replace publication, fail-closed existing-destination `overwrite=true`, source replacement/mutation, zero-byte files, >4 MiB files, missing/repeated completion, offsets, checksum/size mismatch, cancellation at each blocking boundary, deadline equality, task duplicates, bounded shutdown, and descriptor cleanup;
- focused Control-client tests proving exact intent/cancel routing and result serialization;
- real default-limit gRPC integration proving every frame remains at most 256 KiB, Control and Transfer use distinct underlying connections, heartbeat and an ordinary bounded operation complete during backpressured transfer, and no `RESOURCE_EXHAUSTED` message-size error occurs;
- `git diff --check`; and
- normal pre-commit hooks during commit.

No generated client command is required unless protobuf source changes. Any protobuf change is scope drift and requires updating this plan before generation.

## Scope-drift check

Before review and commit, compare the Phase 4 base to the Phase 5 head and confirm:

- only shared Runner client support, Runner transfer/filesystem implementation, the bounded download commit-barrier settlement correction, focused tests, test-only integration metadata, and this phase plan changed;
- the commit-barrier correction does not authorize byte access after logical expiry, revive a terminal attempt, or weaken exact attempt/generation/dispatch/manifest fencing;
- no Server/Worker feature consumer calls the new transfer service;
- no Exchange, Artifact, External Channel, provider, Helm, Kubernetes, or deployment behavior changed;
- no Runtime Control state or storage authority moved into Runner;
- no bucket, object key, object handle, URL, credential, or provider topology entered Runner-facing messages or logs;
- no complete-file buffer was introduced in Runner, Control, coordination, or Redis paths;
- no gRPC message-size option was added; and
- no same-UID mutable named staging path or unsafe existing-destination replacement fallback was added; Phase 9 protected staging and deployment isolation remain deferred; and
- no compatibility fallback, legacy inline-binary route, spec promotion, or future-phase cleanup was included.
