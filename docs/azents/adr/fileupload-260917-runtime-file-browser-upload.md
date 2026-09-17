---
title: "Runtime File Browser Direct Object Transfer Decisions"
created: 2026-09-17
tags: [runtime, files, workspace, frontend, architecture, s3]
document_role: primary
document_type: adr
snapshot_id: fileupload-260917
---

# Runtime File Browser Direct Object Transfer Decisions

- Snapshot: `fileupload-260917`
- Requirements: [fileupload-260917/REQ](../requirements/fileupload-260917-runtime-file-browser-upload.md)
- Document reference: `fileupload-260917/ADR`
- Supersedes before implementation: `upload-260917/ADR` and
  `workspaceupload-260917/ADR`

## Decision Status

All material decisions are accepted. The requester selected S3-compatible object
storage as the Workspace Upload byte data plane in both directions: browser ingress
uses a presigned upload request and Runtime delivery uses a presigned download request.
Runtime Control remains the authorization, coordination, finalization, reconciliation,
and cleanup control plane and does not relay file bodies.

## Decision Summary

- `fileupload-260917/ADR-D1` — Use one transient non-Exchange upload operation and
  source lifecycle per selected file.
- `fileupload-260917/ADR-D2` — Upload browser bytes directly to an operation-scoped S3
  ingress target through a presigned request.
- `fileupload-260917/ADR-D3` — Finalize ingress through authenticated metadata and
  checksum verification plus an S3-native immutable-source snapshot.
- `fileupload-260917/ADR-D4` — Keep explicit status, cancel, retry, and immutable ordered
  Runtime delivery attempts.
- `fileupload-260917/ADR-D5` — Keep Runner-issued opaque destination preconditions for
  conflict-fenced overwrite.
- `fileupload-260917/ADR-D6` — Download the immutable source directly from the public
  S3-compatible endpoint into Runner.
- `fileupload-260917/ADR-D7` — Keep Runtime Transfer admission, generation, cancellation,
  integrity, result, and atomic commit authority around the direct download.
- `fileupload-260917/ADR-D8` — Issue the download capability only after an authenticated
  exact-attempt claim RPC.
- `fileupload-260917/ADR-D9` — Make the existing public S3 endpoint and browser CORS
  mandatory Workspace Upload deployment prerequisites and treat Runtime access as
  Platform transfer egress.

## Context

The current Agent profile-image feature already uses a three-step browser upload:
request a presigned PUT ticket, upload the `File` directly to object storage, then call
an authenticated finalize endpoint. Its finalize implementation downloads the complete
object into the API process because a small image must be decoded, validated, resized,
and republished.

The original Workspace Upload design instead streamed the browser body through Main Web,
the public API, and Runtime Control into S3. It then copied the staged object into a
second Runtime Transfer object, read that object back through Runtime Control, and
streamed it to Runner over `DownloadTransfer` gRPC. That preserved the common Runtime
Transfer trust boundary but made application services carry the complete body in both
directions despite object storage already owning the bytes.

The requester selected the existing presigned object-storage path as the data plane.
The final flow is:

```text
Browser --presigned upload--> S3-compatible storage
S3-compatible storage --presigned download--> Runner
```

The bucket remains private. Each URL is a bounded bearer capability for one exact object
operation and expiry. Runtime Control continues to own authorization and operation
state. The design does not grant Browser or Runner S3 credentials, list access, reusable
prefix authority, or write authority outside the exact ingress target.

## Fixed and Derived Outcomes

1. Existing file-browser behavior, Agent Workspace authorization, Runner-reported root,
   path containment, generation fencing, conflict handling, and atomic destination
   publication remain authoritative.
2. Workspace Upload creates no Exchange, Artifact, ModelFile, FilePart, chat attachment,
   or durable product file identity.
3. The browser never sends the upload body through Main Web, the public API application
   path, Runtime Control, Redis, PostgreSQL, control events, or logs.
4. Runtime Control never downloads the verified Workspace upload body for Runtime
   delivery and never sends that body over Runner transfer gRPC.
5. The public S3-compatible endpoint is mandatory. Its reachability does not make the
   bucket public.
6. Browser upload requires the Main Web origin in object-storage CORS. Runner download
   is server-side HTTP and does not require browser CORS.
7. Workspace Upload has no byte-relay fallback when the public endpoint, required CORS,
   checksum contract, or Runtime Platform egress is unavailable.
8. Browser reload and offset resume remain outside scope. Failed browser ingress starts
   a new upload operation from byte zero.
9. A verified immutable source may be reused by new immutable Runtime delivery attempts
   until the upload operation expires or becomes final.
10. Existing Server-to-Runtime consumers keep the common gRPC byte-stream transport.
    Only Workspace Upload uses direct object download in this snapshot.

## Material Decisions

### `fileupload-260917/ADR-D1`: Transient non-Exchange operation and source — Accepted

**Authority:** `fileupload-260917/REQ-1`, `REQ-2`, `REQ-5`, `REQ-6`.

Each selected local file owns one requester-, Workspace-, Agent-, Runtime-, generation-,
and destination-bound upload operation. Its bounded metadata is stored in Memory or
optional Redis with equivalent semantics. Object existence never reconstructs
operation authority.

The operation owns a temporary ingress object, one finalized immutable source object,
ordered delivery attempts, and their cleanup evidence. Successful destination commit,
cancellation, terminal failure, or expiry eventually removes all temporary objects.
Bucket lifecycle remains backup cleanup rather than authorization or primary settlement.

### `fileupload-260917/ADR-D2`: Browser direct presigned upload — Accepted

**Authority:** requester direction on 2026-09-17; `fileupload-260917/REQ-1`, `REQ-2`,
`REQ-4`, `REQ-5`, `REQ-6`.

After create authorizes the exact requester and destination, Runtime Control allocates
an opaque operation-scoped ingress object. The public API returns a short-lived
presigned upload URL and the exact required headers. Browser uploads directly to the
configured public S3-compatible endpoint and reports local upload progress.

The capability is write-only for one opaque object target. It grants no credentials,
read method, listing, arbitrary key choice, or reusable prefix. Main Web and the public
API carry only bounded ticket and operation metadata.

The existing Agent image ticket pattern is the implementation precedent, but Workspace
Upload does not share image category ownership or finalize behavior.

**Rejected alternatives**

- Relaying the body through Main Web, API, and Runtime Control duplicates bandwidth and
  makes application availability part of a transfer already served by object storage.
- Creating an Exchange file first adds an unrelated durable product lifecycle.
- Giving browser S3 credentials or arbitrary key authority is broader than one upload.

### `fileupload-260917/ADR-D3`: Authenticated finalize and immutable S3 snapshot — Accepted

**Authority:** `fileupload-260917/REQ-2`, `REQ-4`, `REQ-5`.

Browser calls finalize only after its direct upload succeeds. Finalize reauthorizes the
exact requester, operation revision, Workspace, Agent, Runtime, generation, and expiry.
It verifies the ingress object's exact size, S3-validated checksum, and current object
identity without downloading the complete body.

The browser computes SHA-256 in bounded slices outside the UI thread and supplies the
required checksum header signed by the upload ticket. Object storage rejects a checksum
mismatch. Finalize reads authoritative object attributes, compares them with the
operation manifest, and snapshots the exact ingress object to an immutable source key
through an ETag- or version-fenced S3-native copy. It then verifies the source
attributes before recording the source handle and first delivery attempt.

The snapshot prevents a still-live upload URL from replacing the source used by Runner.
The ingress object can be deleted only when a replay can no longer affect finalized
source authority; orphan and lifecycle cleanup cover late or recreated residue.

If the configured S3-compatible backend cannot provide the required checksum and
conditional-copy semantics, Workspace Upload readiness fails. Runtime Control does not
fall back to complete-body validation.

**Rejected alternatives**

- Reusing Agent image finalize would download up to the complete Workspace upload into
  application memory and defeats the direct data plane.
- Trusting browser-reported size, checksum, ETag, or success without object-store
  verification permits incomplete or substituted sources.
- Using the mutable ingress object directly leaves finalized delivery exposed to URL
  replay until ticket expiry.

### `fileupload-260917/ADR-D4`: Explicit operation and immutable delivery attempts — Accepted

**Authority:** `fileupload-260917/REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`.

Create, finalize, status, cancel, and eligible Runtime-delivery retry are separate
operations over one stable public upload identity. Finalize is single-use and
revision-fenced. Delivery retry appends a new child attempt and never reactivates a
terminal child.

Browser ingress failure requires a new upload operation. Runtime delivery failure may
reuse the retained immutable source within the operation lifetime. Each retry starts
at byte zero and receives a fresh delivery identity and download capability.

### `fileupload-260917/ADR-D5`: Opaque conflict-fenced overwrite — Accepted

**Authority:** `fileupload-260917/REQ-3`, `REQ-4`.

Runner captures an opaque destination precondition at the original no-overwrite commit
boundary. Explicit overwrite retry carries that exact token into a new delivery attempt.
Runner reopens and compares the destination under the commit lock before atomic
replacement. Changed, missing, symlinked, cross-path, cross-generation, or expired
evidence produces another conflict.

### `fileupload-260917/ADR-D6`: Runner direct presigned download — Accepted

**Authority:** requester direction on 2026-09-17; `fileupload-260917/REQ-2`, `REQ-4`,
`REQ-5`, `REQ-6`.

Runner downloads the immutable source directly from the existing public S3-compatible
endpoint into a workspace-local temporary file. It hashes bytes while streaming,
requires exact size and SHA-256, fsyncs the completed temporary file, and then performs
the existing symlink-safe atomic no-overwrite or conflict-fenced overwrite commit.

Runtime Control does not create a second Runtime Transfer download object, read the
source body, or invoke `DownloadTransfer` for this consumer.

### `fileupload-260917/ADR-D7`: Retain Runtime Transfer coordination authority — Accepted

**Authority:** `fileupload-260917/REQ-2` through `REQ-6`; unchanged Runtime Transfer
lifecycle and integrity authority.

The Runtime Transfer coordinator remains authoritative for admission, transfer and
attempt identity, Runtime and desired generation, accepted Runner generation, deadline,
cancellation, dispatch, terminal result, and exact result projection. The direct URL is
only a byte-read capability and cannot authorize destination commit on its own.

Runner cancels the active HTTP request and deletes its local temporary file when the
exact transfer is cancelled, its control ownership ends, or its deadline expires.
Success wins over a later cancellation only after the atomic destination commit is
confirmed.

### `fileupload-260917/ADR-D8`: Exact-attempt download claim RPC — Accepted

**Authority:** requester approval on 2026-09-17; `fileupload-260917/REQ-4`, `REQ-5`.

The queued Runner transfer intent remains metadata-only. Runner invokes an authenticated
claim RPC with the exact transfer and attempt identity. Runtime Control revalidates the
current Runner generation, active state, deadline, expected source manifest, and claim
ownership before returning a short-lived presigned GET URL.

The URL is not stored in Redis, Runner Control request history, status, result, logs, or
metrics. Idempotent renewal for the same active claim may issue a fresh URL only within
the original attempt deadline and always restarts HTTP download at byte zero.

Embedding the URL in the queued intent was rejected because it would retain a bearer
secret in coordination and broaden accidental disclosure.

### `fileupload-260917/ADR-D9`: Mandatory public endpoint, CORS, and Platform Runtime egress — Accepted

**Authority:** requester approval on 2026-09-17; `fileupload-260917/REQ-4`, `REQ-5`,
`REQ-6`.

`objectStorage.external.publicEndpoint` becomes a required deployment value for
Workspace Upload and signs both browser upload and Runner download requests. The Main
Web origin must be allowed by bucket CORS for the exact upload methods and required
headers.

Kubernetes Runtime network enforcement treats the endpoint as Platform transfer egress
in `direct`, `proxy_required`, and `no_network` modes without granting general customer
network authority. Deployment validation must prove the endpoint is representable by
stable managed network authority and reachable with valid TLS and DNS or explicit host
mapping.

The private bucket policy continues to deny anonymous access. Public endpoint means
network-reachable signing target, not public object readability.

## Consequences

The complete byte path is owned by object storage. Runtime Control capacity is governed
by bounded metadata operations, S3 attribute/copy requests, reconciliation, and cleanup
rather than file throughput. Availability now depends on the public endpoint, CORS for
browser ingress, Platform Runtime egress for Runner download, and compatible checksum
and conditional-copy semantics.

The Design must remove the unmerged Main Web/API/Runtime Control upload-body stream,
Workspace source multipart writer, Workspace-to-Runtime transfer-object copy, and
Workspace use of `DownloadTransfer`. It must retain and adapt operation state,
reconciliation, retry, cancellation, conflict evidence, and cleanup.
