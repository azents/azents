---
title: "Runtime File Transfer Requirements"
created: 2026-07-25
updated: 2026-07-25
tags: [runtime, files, transfer, transport]
document_role: primary
document_type: requirements
snapshot_id: transfer-260725
---

# Runtime File Transfer Requirements

- Snapshot: `transfer-260725`
- Document reference: `transfer-260725/REQ`

## Problem

Azents moves complete files between server-side or provider-side sources and an Agent
Runtime. The current Runtime control path stores request bodies as chunks internally but
reassembles them into one control-protocol message before delivery to the Runner. Runtime
file content in the opposite direction is also returned through control-operation events.
As a result, an otherwise accepted file can exceed the control transport's message limit,
disconnect the complete Runner control stream, and eventually appear to the Agent as a
generic timeout.

A Slack attachment of approximately 6 MiB exposed this failure: the Agent explicitly
requested the file, but the transfer did not complete because the Runtime control client
received a 4,764,505-byte message while its maximum message size was 4,194,304 bytes.
Increasing that message limit would retain the same coupling and move the failure to a
larger file rather than provide a reliable file-transfer boundary.

## Primary Actor

An Agent performing a file-bearing task on behalf of a user through its Agent Runtime.

## Primary Scenario

A Slack participant sends an invocation containing a supported 6 MiB attachment. The
Agent explicitly selects that attachment and requests materialization at an authorized
Runtime path. Azents transfers the complete file through the Runtime file-transfer
capability without embedding the file body in a control RPC message. The destination is
reported successful only after the complete expected bytes are available, while the
Runner control channel remains healthy and responsive.

## Supporting Scenarios

- The Agent imports an Exchange file, Artifact, or current-run managed file into the
  Runtime through the same server-to-Runtime transfer capability.
- The Agent presents or publishes a Runtime file, and Azents transfers it from the Runtime
  to a server-side or provider-side consumer through the same Runtime-to-server transfer
  capability.
- A trusted source file that already exists in internal object storage is copied or
  promoted to another internal object-storage destination without an application service
  downloading and re-uploading the same complete byte sequence.
- An External Channel reply streams one or more Runtime files to its provider without
  routing their bodies through control-operation messages.
- A manipulated or malformed Runner attempts to access another transfer, exceed an
  admitted size, reorder chunks, or submit invalid completion metadata, and the trusted
  system boundary rejects the attempt without exposing internal storage access.
- A transfer is cancelled, times out, loses connectivity, or exceeds its applicable size
  policy without disconnecting unrelated Runtime control traffic.
- Ordinary process and filesystem control operations continue while a bounded file
  transfer is active.

## Goals

- Provide one common bidirectional Runtime file-transfer capability for all Azents
  features that move complete files across the Server/Runtime boundary.
- Keep file-transfer bytes separate from Runtime control requests, replies, progress, and
  lifecycle traffic.
- Keep internal transfer storage, credentials, object identity, and topology hidden from
  Runtime Runners behind a versioned transfer RPC contract.
- Support every file accepted by the applicable Azents and provider size policies without
  imposing the control protocol's per-message limit as a lower ceiling.
- Keep Worker, Runtime Control, and Runner memory use bounded independently from the total
  transferred file size.
- Keep unchanged object-to-object movement inside internal object storage instead of
  relaying complete file bodies through application memory.
- Preserve exact completion, cancellation, authorization, and failure semantics so an
  Agent is never told that a partial or unverified transfer succeeded.
- Surface a concrete transfer failure promptly instead of degrading a known transport
  failure into a later generic operation timeout.

## Non-Goals

- Changing External Channel attachment discovery, locator authorization, provider scope,
  file-mode support, or publication semantics established by `files-260723`.
- Reclassifying ordinary `file.read`, `file.write`, `file.edit`, or `file.apply_patch`
  operations as file upload or download.
- Moving arbitrary large command, patch, process-output, or other operation payloads to
  the file-transfer capability.
- Automatically creating ExchangeFile, Artifact, ModelFile, or FilePart resources merely
  to relay a Runtime transfer.
- Exposing internal object-storage URLs, object keys, credentials, SDK contracts, or
  provider topology to Runtime Runners.
- Eliminating deliberate bounded content inspection or transformation when a product
  feature requires validation, preview generation, normalization, or another byte-changing
  operation.
- Changing provider-native transfer protocols or provider-owned file-size restrictions.
- Requiring interrupted transfers to resume from their previous byte offset in the first
  delivery of this capability.
- Preserving mixed-version or backward-compatible Runtime Control and Runner operation
  during the transfer protocol cutover.

## Requirements

### REQ-1. Complete server-to-Runtime file transfer

Azents must transfer an authorized complete file from a server-side or provider-side
source to an authorized Runtime destination without carrying its body inside a Runtime
control request.

**Acceptance criteria**

- The primary 6 MiB Slack attachment scenario completes successfully under the existing
  default Runtime control message-size configuration.
- Any file accepted by the applicable product and provider limits can be transferred
  without requiring one control-protocol message proportional to the file size.
- The transfer preserves the expected byte count and content from the admitted source.
- The requested destination is reported successful only after the complete file is
  available according to the destination publication contract.
- A failed or cancelled transfer is not reported as a successful Runtime file.
- Existing destination authorization and overwrite policies remain enforced.

### REQ-2. Complete Runtime-to-server file transfer

Azents must transfer an authorized complete Runtime file to a server-side or
provider-side consumer without carrying its body inside Runtime control-operation reply
events.

**Acceptance criteria**

- `present_file`, outbound External Channel publication, and other complete-file consumers
  can obtain Runtime bytes through one shared transfer capability.
- A file accepted by the applicable product and provider limits does not require a series
  of ordinary model-visible `file.read` operations or Base64 control events to cross the
  Runtime boundary.
- The consumer receives exactly the bytes belonging to the successful transfer.
- A missing, changed, truncated, oversized, unauthorized, failed, or cancelled source is
  not reported as a successful complete transfer.

### REQ-3. Independent control and binary transfer behavior

Runner control RPC traffic and file-transfer streaming traffic must have independent
payload and failure boundaries, even when Runtime Control terminates both contracts.

**Acceptance criteria**

- Runtime control requests and events contain transfer identity, metadata, authorization
  outcome, progress, cancellation, and terminal status, but not file-body chunks.
- File bodies are not serialized into a repeated field or Base64 field of a Runner control
  request or operation event.
- File bodies cross the Runtime boundary only through the dedicated transfer streaming
  contract terminated by Runtime Control.
- Runtime Coordination Store and its Redis implementation do not relay or buffer
  file-body bytes.
- A file-transfer size rejection, data-path disconnect, or transfer timeout does not by
  itself disconnect the Runner control channel.
- Unrelated lifecycle, heartbeat, cancellation, process, and bounded filesystem control
  operations remain routable while a file transfer is active, subject to their existing
  scheduling limits.
- Transfer completion or failure is correlated unambiguously with its initiating control
  operation.

### REQ-4. Bounded streaming and backpressure

File transfer must use bounded incremental data movement rather than whole-file buffering
at each service boundary.

**Acceptance criteria**

- Worker, Runtime Control, and Runner do not need to hold the complete file body in memory
  merely to relay it across the Runtime boundary.
- The sender cannot produce unbounded buffered data when the receiver or downstream
  provider is slower.
- Configured per-file and aggregate product limits are enforced against actual transferred
  bytes, not only declared metadata.
- Concurrent transfers have explicit bounded admission and resource use so they cannot
  starve Runtime control traffic.
- Transfer buffers and temporary state are released after success, failure, cancellation,
  timeout, or connection loss.

### REQ-5. Integrity and destination safety

A successful transfer must identify one complete byte sequence and must not expose an
incomplete destination as the completed file.

**Acceptance criteria**

- The receiver verifies the final transferred length against the admitted transfer
  metadata.
- Corruption, duplication, omission, or out-of-order data that can affect the resulting
  file is detected before success is reported.
- Server-to-Runtime transfer publishes the final destination only after successful
  verification, or otherwise provides an equivalent guarantee that incomplete content is
  not mistaken for the completed destination.
- Failure cleanup does not delete or overwrite an earlier valid destination unless the
  caller explicitly authorized replacement and the replacement completed successfully.
- Logs and results do not contain file-body content.

### REQ-6. Cancellation and terminal failure reporting

A transfer must have bounded cancellation and terminal settlement independent of the
Runner control stream lifecycle.

**Acceptance criteria**

- A caller can cancel an active transfer through its control operation.
- Cancellation stops further byte transfer, releases in-process buffers, immediately
  invalidates the transfer object, and initiates best-effort physical cleanup.
- A known size-limit, authorization, integrity, connectivity, or protocol failure reaches
  the caller as a corresponding transfer failure rather than only as `Runtime operation
  timed out`.
- A control-channel reconnect does not silently convert a known completed, failed, or
  cancelled transfer into an unknown success.
- Retrying an unsuccessful transfer is safe and does not cause a prior partial attempt to
  be presented as the completed file.

### REQ-7. Shared transfer contract across features

Features that move complete files across the Server/Runtime boundary must use one common
transfer contract rather than feature-specific binary RPC payloads.

**Acceptance criteria**

- External Channel download and publication, Exchange/Artifact/managed-file import, and
  Runtime file presentation can use the common transfer capability in their applicable
  direction.
- Feature services retain their existing authorization, source resolution, destination,
  provider, and user-visible result responsibilities.
- Adding another complete-file transfer consumer does not require adding file-body fields
  to the Runner control protocol.
- Ordinary text-oriented or bounded filesystem operations remain separate control
  operations and are not implicitly redirected through file upload/download.

### REQ-8. Transfer observability without content exposure

Operators must be able to distinguish control-plane failures from file data-plane
failures and identify where a transfer stopped.

**Acceptance criteria**

- Structured diagnostics identify transfer direction, phase, bounded byte counts,
  duration, terminal classification, Runtime identity, and correlation identity.
- Metrics distinguish admission rejection, source failure, destination failure,
  cancellation, timeout, integrity failure, and data-path disconnect.
- The original gRPC message-size failure class is directly diagnosable and cannot surface
  solely as a later generic operation timeout.
- Diagnostics exclude file bodies, provider credentials, private provider URLs, bearer
  headers, and other transfer secrets.

### REQ-9. Untrusted Runner and implementation-hiding boundary

Runtime Runner must be treated as an external and potentially manipulated component.
Runtime Control must mediate file transfer without exposing internal transfer-storage
implementation or authority to the Runner.

**Acceptance criteria**

- The Runner receives only the versioned control and binary-stream RPC fields required to
  execute its side of one authorized transfer.
- The Runner never receives an internal object-storage bucket name, object key, presigned
  URL, storage credential, IAM authority, or SDK-specific operation.
- For Runtime-to-server transfer, the Runner streams bounded bytes to Runtime Control and
  Runtime Control writes the admitted transfer to internal temporary storage on the
  Runner's behalf.
- For server-to-Runtime transfer, Runtime Control reads the authorized internal temporary
  object and streams bounded bytes to the Runner without exposing the object's storage
  address.
- Runtime Control authenticates the Runner and verifies current Runtime identity,
  generation, transfer identity, direction, admitted size, and authorization before
  accepting or releasing bytes.
- Runner-provided paths, sizes, checksums, ordering, completion claims, and other metadata
  are treated as untrusted and validated at the trusted boundary.
- A Runner cannot use one transfer to read, overwrite, append to, complete, or cancel
  another Runtime's, Agent's, Session's, or direction's transfer.
- Malformed, duplicated, omitted, reordered, oversized, late, or unauthorized stream
  messages fail only the affected transfer and do not expose internal storage details.
- Internal temporary-storage implementation can change without changing the Runner RPC
  contract or requiring a Runner to understand the replacement.

### REQ-10. Object-store-native movement for already-stored files

When an admitted source already exists in trusted internal object storage and the next
trusted destination is another internal object-storage object, Azents must complete the
unchanged file movement without materializing the complete body in an application service
solely to upload the same bytes again.

**Acceptance criteria**

- Exchange, Artifact, and other authorized internal object sources can become a Runtime
  transfer source through an object-store-native copy, promotion, or equivalent trusted
  reference operation rather than a complete application download followed by re-upload.
- A successful Runtime-to-server transfer stored as an internal temporary object can
  become an Exchange, Artifact, or other internal object destination without a complete
  application download followed by re-upload of unchanged bytes.
- The destination object and its product metadata become visible only after the trusted
  object operation and required authorization, size, integrity, and ownership checks
  succeed.
- Failure cleanup deletes only temporary or uncommitted destination objects owned by the
  failed attempt and does not alter the authoritative source object or its retention.
- Features that require content inspection or transformation use bounded reads or an
  explicit transformation pipeline; ordinary unchanged object movement does not require
  whole-file application buffering.

### REQ-11. Optional transfer-state backend

The file-transfer capability must not make Redis mandatory for a standalone
single-process Azents deployment. Transfer state must be accessed through one
implementation-neutral contract with both process-local and shared deployment
implementations.

**Acceptance criteria**

- A single Runtime Control process can execute, cancel, and settle complete file
  transfers with an in-memory state implementation and without a Redis dependency
  introduced by the transfer capability.
- A multi-replica Runtime Control deployment uses a shared state implementation, and an
  invalid process-local multi-replica configuration is rejected rather than operating
  with divergent transfer authority.
- Selecting a different state implementation does not change the Runner RPC contract,
  feature-service contract, authorization, integrity, or terminal-result semantics.
- Process-local and shared implementations pass the same transfer-state contract tests.
- Neither implementation stores or relays file-body bytes.

### REQ-12. Short-lived transfer data retention

Transfer content and metadata must remain short-lived implementation resources rather
than becoming another retained product file or audit store. Physical object deletion is
best effort and must not reverse an already completed feature result.

**Acceptance criteria**

- A transfer object is logically valid for no longer than one hour from attempt creation
  and never beyond the authoritative source's earlier expiration.
- Success, failure, cancellation, timeout, integrity rejection, and supersession trigger
  an immediate best-effort object delete or multipart abort.
- A cleanup failure records bounded diagnostic state and remains eligible for asynchronous
  cleanup, but does not change a successfully completed Runtime destination, product
  publication, or provider delivery into a failure.
- No Runner RPC or trusted consumer can read, publish, or revive a transfer object after
  its logical expiration even when physical storage deletion has not completed.
- Content-free terminal transfer metadata expires no later than one hour after terminal
  settlement.
- Object-storage lifecycle rules provide a coarser final defense for orphan objects and
  incomplete multipart uploads; they are not the mechanism that enforces the one-hour
  logical validity contract.

## Fixed Constraints

- The capability covers both Server-to-Runtime upload and Runtime-to-server download.
- The primary incident scenario is Slack attachment materialization, but the transport
  boundary is shared by every complete-file transfer consumer.
- The existing Runner control stream and the file-body streaming contract are separate:
  file-body bytes must not be embedded in Runner control RPC messages or operation events.
- Runtime Control is the trusted gateway for both transfer directions. Runtime Runners do
  not access internal temporary storage directly.
- Runtime Runner is an external, potentially manipulated component and is trusted only
  within the behavior validated through its authenticated RPC contract.
- Worker and Runtime Runner do not establish a direct binary connection.
- Ordinary `file.read`, `file.write`, `file.edit`, and `file.apply_patch` remain filesystem
  control operations rather than aliases for complete-file upload/download.
- Existing External Channel access, provider authorization, explicit-transfer, size-limit,
  no-automatic-model-input, and no-automatic-product-file-resource contracts remain
  unchanged.
- Existing source and destination lifecycle owners remain authoritative. Temporary
  transfer storage does not become an ExchangeFile, Artifact, ModelFile, FilePart, or
  another user-visible or retained product file resource, and it must not extend the
  source file's product retention.
- Existing S3-compatible workspace object storage is the trusted internal object boundary.
  When both the admitted source and destination are objects, Azents uses object-store-native
  copy, promotion, or equivalent reference semantics instead of an unchanged byte relay.
- Redis is an optional shared-state implementation rather than a mandatory transfer
  dependency. Standalone deployments support process-local state; multi-replica
  deployments require an implementation with shared coordination semantics.
- Transfer object validity has a fixed one-hour maximum. Physical deletion is best
  effort, while authorization and transfer-state checks enforce the expiration
  synchronously.
- Transfer authentication and authorization must remain bound to the initiating Agent,
  Runtime, Session context when applicable, and current Runtime generation.
- No legacy inline-binary fallback is required after a transfer consumer adopts the new
  contract.
- Runtime Control, Runtime Runner, and complete-file transfer consumers may use one
  coordinated protocol cutover. Supporting older Runner protocol versions during that
  cutover is not required, and brief Runtime unavailability is acceptable.

## Open Assumptions

- Runtime deployments and server-side transfer producers can reach the selected temporary
  transfer boundary without weakening the existing outbound-connection security model.
- Runtime Control can be provisioned and scaled for bounded streaming throughput in
  addition to its existing control-traffic responsibilities.
- Existing configured product limits remain the authority for maximum accepted file size;
  this snapshot does not choose new user-facing limits.
- First delivery may retry an interrupted transfer from the beginning; offset resume is an
  ADR/design decision only if required for correctness or operational feasibility.
- Provider adapters may continue streaming directly between the common Runtime transfer
  boundary and provider-native HTTP transfer APIs.
- The selected S3-compatible storage supports trusted server-side object copy semantics;
  the design may require multipart copy for objects beyond a backend's single-copy limit.

## Confirmation

Confirmed by the requester on 2026-07-25 before ADR and design decisions began.
The requester confirmed a shared bidirectional complete-file transfer capability, an
untrusted external Runtime Runner boundary, no direct Worker-to-Runner binary connection,
and an implementation-hiding Runtime Control transfer gateway.
The requester additionally confirmed that unchanged movement between existing internal
objects must remain inside S3-compatible storage rather than downloading and re-uploading
the complete body through application services.
The requester additionally confirmed that Redis is optional and that transfer state must
have an interface-backed in-memory implementation as well as a shared Redis
implementation.
The requester additionally confirmed immediate best-effort deletion with a one-hour
maximum transfer-object and terminal-metadata TTL.
The requester additionally confirmed that backward compatibility and mixed-version
operation may be omitted because the current deployment has one user and can use a
coordinated cutover.
