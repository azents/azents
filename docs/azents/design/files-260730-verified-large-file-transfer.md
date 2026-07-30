---
title: "Verified Large External File Transfer Design"
created: 2026-07-30
updated: 2026-07-30
tags: [external-channel, files, runtime, transfer, scheduler]
document_role: primary
document_type: design
snapshot_id: files-260730
implemented: 2026-07-30
---

# Verified Large External File Transfer Design

- Snapshot: `files-260730`
- Document reference: `files-260730/DESIGN`
- Requirements: [`files-260730/REQ`](../requirements/files-260730-verified-large-file-transfer.md)
- ADR: [`files-260730/ADR`](../adr/files-260730-verified-large-file-transfer.md)

## Overview

This design makes large inbound External Channel attachment delivery explicit, verified,
and fair. An attachment has a visible declared byte size; the Agent must repeat that exact
value in `download_external_file`. The trusted provider adapter verifies the selected size
against current provider metadata and the authenticated HTTP response `Content-Length`,
then S3 staging verifies the received byte count before a Runtime transfer can begin.

The Runtime Control path no longer uses active file count or aggregate bytes as a reason
to deny admission. Instead, active download and upload streams participate in a
chunk-granular round-robin scheduler. A file advances by one bounded chunk, then returns
to the tail while another eligible file waits. This protects fairness without treating a
large known attachment as unsafe.

## Traceability

| Requirement | ADR decisions | Design mechanisms |
| --- | --- | --- |
| `files-260730/REQ-1` | `files-260730/ADR-D1`, `files-260730/ADR-D4` | 500 MiB inbound ceiling; no aggregate admission byte limit |
| `files-260730/REQ-2` | `files-260730/ADR-D2` | Required `expected_size_bytes`; visible exact byte size |
| `files-260730/REQ-3` | `files-260730/ADR-D1`, `files-260730/ADR-D2` | Metadata/header/body attestation and immutable staging verification |
| `files-260730/REQ-4` | `files-260730/ADR-D3`, `files-260730/ADR-D4` | Per-file FIFO, round-robin chunk scheduler, queue lifecycle cleanup |
| `files-260730/REQ-5` | `files-260730/ADR-D2`, `files-260730/ADR-D3`, `files-260730/ADR-D4` | Controlled errors, transfer-domain gRPC translation, cleanup/fencing |

## Current Behavior and Gaps

- `ExternalChannelFileMetadata.declared_size` is projected and rendered, but
  `DownloadExternalFileInput` contains only `file`, `path`, and `overwrite`.
- Slack and Discord file metadata is refreshed before download, but the request does not
  bind the refreshed value to an Agent-selected size.
- Provider stream openers expose an iterator only; they discard HTTP response headers,
  including `Content-Length`.
- `DeferredProviderServerToRuntimeSource` already rejects an actual body size that differs
  from `metadata.size`, but cannot verify response-header evidence.
- `RuntimeTransferStateStore.admit()` rejects active-attempt and aggregate-byte capacity
  overflow. `RuntimeRunnerTransferGrpcServicer` also returns `RESOURCE_EXHAUSTED` rather
  than waiting whenever its whole-stream semaphore is locked.
- The existing Server-to-Runtime boundary translates raw coordinator gRPC failures into a
  controlled domain failure. This design preserves that boundary and classifies a
  `RESOURCE_EXHAUSTED` admission result as `ADMISSION` without exposing gRPC details.

## Attachment Size Visibility and Tool Contract

### Rendering

Keep the existing deterministic `Declared size: <n> bytes` attachment rendering in
External Channel model context and continuity. A file with absent or invalid
`declared_size` remains visible as `unknown` but is not eligible for the download tool.
No display rounding is used for the tool contract: the integer byte value is the value
that the Agent must pass.

### Tool input

Extend `DownloadExternalFileInput`:

```text
download_external_file(
  file: <opaque locator>,
  expected_size_bytes: <integer>,
  path: <absolute Runtime path>,
  overwrite: false
)
```

`expected_size_bytes` is required, positive-or-zero, and bounded at 500 MiB. Tool
description text explicitly says to copy the `Declared size` value shown with the
attachment. The tool passes the value unchanged to `ExternalChannelFileTransferService`.

The tool result remains path, filename, media type, and verified byte count. A controlled
failure describes the user-safe condition (for example, selected size changed or provider
response has no matching size) and never includes provider URLs, credentials, S3 keys, or
gRPC status details.

## Verified Provider Download

### Size-attestation sequence

For Slack and Discord, inbound download uses this ordered sequence:

1. Resolve the active binding, capability, credentials, and opaque locator under the
   existing authorization rules.
2. Fetch current provider attachment metadata.
3. Require a non-negative current metadata size equal to `expected_size_bytes` and not
   greater than the effective inbound policy ceiling or 500 MiB.
4. Open the authenticated provider HTTP response without passing body authority to the
   Runtime.
5. Require exactly one valid `Content-Length` decimal integer equal to the selected size.
6. Stream body chunks to the Control-owned multipart preparation object, keeping a running
   byte count and SHA-256.
7. Abort multipart staging on short body, oversized body, header mismatch, cancellation,
   provider failure, or deadline.
8. Complete and copy the immutable object only after the counted body equals the selected
   size. Revalidate current provider metadata and active binding before Runtime dispatch.
9. Stream the verified immutable object to the Runtime and commit the destination only
   after the existing Runner result/consumer acknowledgement succeeds.

A body is never accepted merely because it is smaller than the configured maximum; it
must match the one exact selected size. Existing S3 metadata and immutable-copy checks
remain a fourth trusted storage verification after the three required size attestations.

### Provider HTTP abstraction

Replace iterator-only provider stream openers with an owned response abstraction that
contains:

- parsed `content_length: int | None`; and
- the bounded async body iterator.

Slack and Discord HTTP adapters parse the response header before exposing any body chunk.
They reject duplicate, non-decimal, negative, or unavailable values as missing/invalid
size evidence. Tests use fake owned responses rather than real provider URLs.

### Inbound policy

Set the External Channel inbound default and configured maximum to 500 MiB. The service
always computes `min(system_setting_limit, 500 MiB)`, so an operator can lower a local
policy but cannot silently permit a larger file. Existing outbound fields and their
contracts do not change.

## Round-Robin Chunk Scheduling

### Scheduler ownership

Add an internal `RoundRobinChunkScheduler` to the Runtime Runner transfer gRPC servicer.
Each `DownloadTransfer` and `UploadTransfer` registers one participant after
authentication, transfer identity fencing, and object/header verification. A participant
contains its transfer identity, next-chunk coroutine, completion future, cancellation
signal, and monotonic file-local sequence.

The scheduler owns the configured number of in-flight chunk permits. A participant does
not hold a permit for its whole file. It receives one chunk, is appended to the tail if it
has more data, and only then can receive a later chunk. The next eligible participant is
therefore selected before the same file can advance again.

The scheduler is process-local because it owns live gRPC stream continuations; it never
stores chunk bytes, provider authority, or a second durable job record. Existing Runner
connection fencing makes a Runtime's active transfer streams connection-scoped. A Control
restart or disconnect terminates those streams through the existing transfer lifecycle;
the normal recovery/cleanup path handles the resulting attempt state.

### Download flow

1. `DownloadTransfer` authenticates and claims the exact transfer as today.
2. It verifies the immutable object once, opens its S3 iterator, and registers a download
   participant.
3. Each yielded `DownloadTransferFrame` is supplied only after the scheduler grants that
   participant's next turn.
4. The participant verifies chunk bounds, offset, progress, stream lease, and deadline
   before yielding the chunk, then yields scheduling control.
5. EOF validates final size and SHA-256, then follows the existing verification,
   acknowledgement, settlement, and cleanup flow.

### Upload flow

`UploadTransfer` applies the same scheduler to accepted inbound Runner chunks. The
scheduler grants the next multipart/body chunk turn, validates its expected offset and
maximum size, persists the part, and rotates the participant. Opening and terminal frames
are not data chunks and are not delayed behind another file's body chunk.

### Queue lifecycle

- Participants are appended in registration order, producing FIFO order for first chunks.
- A participant is removed before its next turn when cancelled, expired, fenced, failed,
  or complete.
- Scheduler shutdown fails waiting participants through the existing controlled stream
  error/terminal settlement path; it does not leave a waiter task or permit behind.
- A slow S3 operation consumes one in-flight chunk permit only while that chunk I/O is
  executing. Other eligible files can consume other permits up to configured concurrency.
- `maxConcurrentDownloads` and `maxConcurrentUploads` name the maximum in-flight chunks,
  not the number of accepted files.

## Admission and Runtime Transfer State

`RuntimeTransferConfig` and both memory/Redis stores retain durable transfer lifecycle,
lease, deadline, and one-current-attempt fencing. Remove `per_runtime_attempts`,
`deployment_attempts`, `per_runtime_bytes`, and `deployment_bytes` from admission
rejection logic and Runtime Control/Helm configuration. The attempt/byte counters used
only for those checks are removed as well.

Admission still rejects invalid identity, stale/deadline-expired work, a source whose
selected size exceeds 500 MiB or the effective inbound setting, and an overlapping active
attempt for the same transfer ID. It does not reject a valid independent file because
other files are active. This eliminates the coordinator-side `RESOURCE_EXHAUSTED`
condition caused by routine transfer load.

The Server-to-Runtime client boundary continues to translate any residual raw gRPC
exception to `ServerToRuntimeTransferError`; `RESOURCE_EXHAUSTED` maps to the bounded
`ADMISSION` failure class and External Channel maps that to a controlled write failure.

## Security and Failure Handling

- Only trusted server services read provider metadata, headers, provider bodies, and S3
  objects. The Runner receives only verified transfer frames and opaque transfer identity.
- No attachment byte body, provider URL, bearer token, `Content-Length` header value
  beyond the selected integer, or scheduler queue payload is persisted to External Channel
  records or model context.
- Header/metadata/body mismatch aborts the multipart upload and does not dispatch the
  Runtime transfer.
- Runtime destination commit remains atomic through the Runner's existing temporary-file
  and verified result path.
- Cancellation and deadline propagation preserve `asyncio.CancelledError`; cleanup
  failures remain server diagnostics and do not leak raw exceptions through tool output.

## Migration, Rollout, and Rollback

The External Channel file System Setting schema remains version 1. Its inbound default
and maximum change to 500 MiB. Existing explicitly lower stored limits continue to apply;
new installations receive 500 MiB. No transferred bytes or provider authorization are
migrated.

Remove obsolete Runtime Control transfer admission environment variables and Helm values.
Deployments that retain stale environment variables are harmless because settings ignore
unknown environment values, but chart output no longer advertises the obsolete limits.

Rollback restores the prior application/chart version. New transfers already staged are
handled by the existing versioned transfer record, timeout, and orphan multipart cleanup;
there is no new durable scheduler state to migrate or roll back.

## Test Strategy

### E2E primary matrix

The primary E2E journey provisions a deterministic External Channel provider fixture and
Runtime, exposes a sized attachment, invokes `download_external_file`, and validates the
resulting Runtime file checksum and size. The matrix covers:

| Scenario | Expected evidence |
| --- | --- |
| 500 MiB valid attachment | Tool success; Runtime checksum/size match; no raw transport error |
| tool size differs from displayed metadata | Controlled failure before provider body request |
| missing/mismatched `Content-Length` | Controlled failure; no Runtime destination commit |
| short/long body | Controlled failure; multipart cleanup; no Runtime destination commit |
| two multi-chunk files | Interleaved per-file chunk trace in round-robin order |
| queued cancellation | No later chunk for cancelled file; other file continues |

The 500 MiB fixture uses deterministic generated bytes and local object storage. It is
marked integration-heavy and runs in the Runtime Provider E2E environment when that
fixture/profile is available. CI retains deterministic unit and socket-level coverage for
every matrix row; the optional live/provider E2E row skips only when credentials or the
large-fixture environment are unavailable and records the prerequisite reason.

### Focused unit and integration coverage

- Core/tool tests cover required `expected_size_bytes`, rendering, bounds, and controlled
  errors.
- Slack/Discord adapter tests cover current metadata mismatch, absent/malformed/multiple
  `Content-Length`, and body mismatch without exposing a URL.
- Provider staging tests cover exact 500 MiB boundary through chunked synthetic streams,
  abort cleanup, and no commit on mismatch.
- Memory and Redis store contract tests prove valid independent admissions do not fail
  due to active bytes/counts.
- Runner transfer socket tests assert fair ordering, no `RESOURCE_EXHAUSTED` while work is
  queued, cancellation removal, deadlines, and no permit leaks.
- Existing External Channel and Runtime Control focused suites remain required regression
  checks.

### CI policy

The PR must pass formatting, lint, type checks, generated-protobuf checks if protocol
changes are required, focused Python tests, chart render tests, documentation validation,
and required GitHub CI checks. The feature is not complete until the single PR is open and
all required CI checks pass.
