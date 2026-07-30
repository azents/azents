---
title: "Verified Large External File Transfer"
created: 2026-07-30
tags: [external-channel, files, runtime, transfer, architecture]
document_role: primary
document_type: adr
snapshot_id: files-260730
---

# Verified Large External File Transfer

- Snapshot: `files-260730`
- Requirements: [`files-260730/REQ`](../requirements/files-260730-verified-large-file-transfer.md)

## Context

External Channel attachment metadata already includes a nullable declared byte size and
the model-facing renderer displays it. The current `download_external_file` tool does
not require that size as input. Provider staging counts received bytes against a metadata
size, but its stream boundary has no HTTP `Content-Length` contract. Runtime Control
tracks active transfer attempt and byte capacity before staging and its Runner transfer
server rejects a request when a download semaphore is occupied. Both rejection paths
surface as gRPC `RESOURCE_EXHAUSTED` to callers unless translated at a higher boundary.

The confirmed Requirements fix these boundaries and they are not decision points:

- one inbound attachment may be up to 500 MiB;
- an Agent must select the exact observed size before body download;
- provider metadata, `Content-Length`, and received bytes must agree; and
- competing files receive chunk-granular round-robin service rather than immediate
  capacity rejection.

## Decision Backlog

| Order | Decision point | Dependency | Status |
| --- | --- | --- | --- |
| DP1 | Inbound size authority and 500 MiB product boundary | None | Accepted as ADR-D1 |
| DP2 | Required expected-size tool contract and HTTP evidence | DP1 | Accepted as ADR-D2 |
| DP3 | Fair chunk scheduler ownership and lifecycle | DP1 | Accepted as ADR-D3 |
| DP4 | Existing byte/attempt admission limits | DP3 | Accepted as ADR-D4 |

## Decisions

### files-260730/ADR-D1. Treat 500 MiB as the inbound per-file product maximum

**Affects:** `files-260730/REQ-1`, `files-260730/REQ-3`

Define one inbound External Channel file maximum of 500 MiB (524,288,000 bytes). The
limit applies to each source attachment individually and is enforced against every size
evidence source. It is not an aggregate Runtime, deployment, or object-store staging
budget. Existing outbound limits remain outside this snapshot.

The existing inbound system-setting value becomes a policy ceiling that may reduce but
never increase the 500 MiB product maximum. New default policy is 500 MiB. This preserves
an operator's ability to impose a smaller deployment policy without making a lower
transfer-capacity setting an implicit product restriction.

**Rejected:** Retaining a 25 MiB or 100 MiB default contradicts the confirmed large-file
scenario. Removing every operator policy limit would eliminate a legitimate deployment
control unrelated to Runtime scheduling.

### files-260730/ADR-D2. Bind explicit selection to three size attestations

**Affects:** `files-260730/REQ-2`, `files-260730/REQ-3`, `files-260730/REQ-5`

Add a required integer `expected_size_bytes` to `download_external_file`. The value must
match the current provider metadata before opening a download response. The authenticated
provider adapter must then require one valid HTTP `Content-Length` that equals that same
value before body iteration. Staging counts bytes and rejects both short and oversized
bodies; it commits an immutable S3 object only when the count also equals the expected
value.

A missing, non-integer, negative, or conflicting value is a controlled failure. The size
is rechecked when provider authority is revalidated before Runtime dispatch, so a changed
file cannot be committed under an earlier selection.

**Rejected:** Trusting only provider metadata leaves the HTTP response unbound to the
selected attachment. Trusting only `Content-Length` permits a changed provider object to
bypass the Agent's explicit selection. Permitting an absent header requires speculative
body reads and violates the confirmed requirement to know the size before triggering.

### files-260730/ADR-D3. Schedule next chunks fairly per Runtime Control transfer connection

**Affects:** `files-260730/REQ-4`, `files-260730/REQ-5`

Replace the reject-on-locked download semaphore with a connection-owned asynchronous
round-robin chunk scheduler. A Runner transfer stream registers its verified transfer
object as one file participant. The scheduler accepts at most the configured number of
in-flight chunk reads globally for that Runtime Control process, but it selects
participants by cycling once through each eligible file before returning to a file that
has more chunks. A participant receives its chunks in offset order.

The Runner maintains one long-lived Runtime Control transfer channel, so all concurrent
transfer streams for that Runner are scheduled by the same serving connection. If the
connection is lost, existing lifecycle fencing and retry/recovery behavior applies; no
unbounded queue state is persisted as an independent product resource.

The analogous upload stream scheduler follows the same participant lifecycle and
round-robin rule. The configured `maxConcurrentDownloads` and `maxConcurrentUploads`
remain controls for in-flight chunks, not complete-file admissions.

**Rejected:** A semaphore held for an entire file lets large files monopolize capacity and
forces later requests to fail. A durable cross-deployment queue adds a new distributed
job lifecycle, persistence policy, and recovery contract that the confirmed requirement
does not need because transfer streams already have connection/lease fencing.

### files-260730/ADR-D4. Remove byte and transfer-count admission as scheduling gates

**Affects:** `files-260730/REQ-1`, `files-260730/REQ-4`, `files-260730/REQ-5`

Remove Runtime and deployment active-byte capacity checks from transfer admission. Also
remove active-attempt capacity checks that reject an otherwise valid transfer before it
can wait for chunk service. Admission continues to enforce identity fencing, deadlines,
source size versus product/provider policy, and one active attempt for the same transfer
identity.

The 500 MiB per-file boundary, explicit size attestations, stream lease, deadline,
cancellation, cleanup, and chunk scheduler are the controlling safety mechanisms.

**Rejected:** Raising numerical byte or attempt limits only postpones rejection and keeps
the wrong complete-file scheduling model. Keeping a hidden aggregate byte admission
budget contradicts the explicit requirement that large, known attachments wait fairly
rather than fail due to unrelated active files.
