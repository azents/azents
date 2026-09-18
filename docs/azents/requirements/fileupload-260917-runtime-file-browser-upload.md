---
title: "Runtime File Browser Upload Requirements"
created: 2026-09-17
updated: 2026-09-17
tags: [runtime, files, workspace, frontend]
document_role: primary
document_type: requirements
snapshot_id: fileupload-260917
---

# Runtime File Browser Upload Requirements

- Snapshot: `fileupload-260917`
- Document reference: `fileupload-260917/REQ`
- Supersedes before implementation: `upload-260917/REQ` and
  `workspaceupload-260917/REQ` because the requester changed both browser ingress and
  Runtime delivery to the existing presigned S3-compatible path

## Problem

The Agent Workspace file browser can inspect, manage, preview, and download Runtime
files, but a Workspace member cannot place a local file directly into the directory
being viewed. The available chat attachment upload creates an Exchange attachment for
conversation use rather than committing a file at an explicit Agent Workspace path.
Users therefore need an indirect Agent action or another file-transfer tool for an
ordinary file-browser upload.

## Primary Actor

A signed-in Workspace member who can access an Agent and its ready Agent Workspace.

## Primary Scenario

The member opens a directory in the Agent Workspace file browser, selects one or more
regular local files, and starts an upload to that directory. The browser shows each
file's progress and terminal result. Every successful file becomes visible at its
selected destination with the original filename. A cancelled, rejected, conflicted,
or failed file does not appear as a partially committed destination, and the member
can retry an eligible failed file without repeating files that already succeeded.

## Supporting Scenarios or Effects

- The destination directory may be the Agent Workspace root, a registered Project, or
  another accessible directory currently represented by the file browser.
- Multiple selected files complete independently, so one failure does not roll back
  files that were already committed successfully.
- An existing destination is never replaced silently; the member receives a conflict
  outcome and may explicitly choose an allowed overwrite action.
- Runtime loss, generation change, destination change, cancellation, transfer expiry,
  or integrity failure produces a bounded per-file failure without publishing partial
  content.
- The browser uploads the admitted file directly to the configured public
  S3-compatible endpoint instead of relaying its body through Main Web, the public API,
  or Runtime Control.
- The Runtime downloads the verified staged object through the existing S3-compatible
  download path instead of receiving file bytes from a Runtime Control gRPC stream.
- A successful upload appears in the current file-browser view without requiring a
  full page reload.

## Goals

- Let an authorized member upload regular local files directly into the selected Agent
  Workspace directory from the existing file browser.
- Provide understandable per-file progress, cancellation, conflict, failure, and retry
  behavior for a multi-file selection.
- Preserve exact file bytes and publish each destination atomically only after the
  complete file has passed the existing Runtime transfer integrity checks.
- Reuse the existing presigned browser upload capability for the local-file-to-staging
  byte path without granting the browser reusable object-storage authority.
- Reuse the existing S3-compatible download capability for the staged-object-to-Runtime
  byte path without granting the Runtime durable object-storage authority.
- Preserve Agent Workspace authorization, current Runtime and Runner generation
  fencing, path containment, and destination-type validation.
- Keep file bodies out of PostgreSQL, Redis coordination, control events, logs, and
  durable Agent or Session history.

## Non-Goals

- Uploading a local directory, preserving a directory tree, extracting an archive, or
  provisioning a Project from an uploaded file.
- Creating a user-visible chat attachment or changing Exchange attachment, Artifact,
  ModelFile, FilePart, or conversation-retention behavior.
- Synchronizing a local folder, watching local changes, or providing offset-based
  resumable upload across browser reloads or devices.
- Changing Agent Workspace move, rename, delete, preview, download, Project registry,
  or worktree semantics.
- Sending files through External Channel bindings or provider attachment protocols.
- Moving file bytes into the persistent Runtime Stream Session or Runner Control
  operation event stream.
- Applying live deployment or Kubernetes changes as part of this design snapshot.

## Requirements

### REQ-1. Upload files to the selected directory

The file browser must let the member select one or more regular local files and upload
each file to the directory that was selected when the upload began.

**Acceptance criteria**

- Upload is available only for a destination that the current file-browser state
  identifies as an accessible directory in a ready Agent Workspace.
- Each admitted file retains its local basename and is addressed to a destination
  inside the current Runner-reported Agent Workspace.
- A successful file appears in the destination listing and can be opened, inspected,
  downloaded, moved, renamed, or deleted through the existing file-browser behavior.
- Local directories and unsupported browser items are rejected before Runtime
  destination mutation.

### REQ-2. Per-file progress, cancellation, and retry

The member must receive an independent observable lifecycle for every selected file and
must be able to cancel an active file or retry an eligible failed file.

**Acceptance criteria**

- Each file exposes queued, uploading, moving to Agent Runtime, succeeded, cancelled,
  conflicted, or failed progress as applicable without representing the whole
  selection as one indivisible transaction.
- While the browser is sending bytes directly to the attempt-bound object-storage
  target, the visible phase is `Uploading`. After authenticated finalization verifies
  and freezes the source and Runtime delivery begins, the visible phase changes to
  `Moving to Agent Runtime`.
- The UI does not present browser ingress completion as complete Workspace upload;
  success is shown only after the Agent Runtime destination commit is confirmed.
- Cancelling one active file does not cancel or roll back another file in the same
  selection.
- Cancellation before destination commit does not publish a partial file; cancellation
  after a confirmed atomic commit does not convert that committed file back to a
  cancelled result.
- Retry creates a new bounded attempt for only the selected unsuccessful file and does
  not implicitly replay a succeeded file.
- Failure copy distinguishes at least invalid destination, conflict, size or admission
  rejection, authorization, Runtime unavailability or fencing, cancellation, integrity
  failure, and unexpected transfer failure when those conditions are known.

### REQ-3. Explicit conflict handling and atomic destination publication

The upload flow must not silently replace an existing destination and must make the
member's overwrite intent explicit.

**Acceptance criteria**

- The default upload attempt fails safely when its destination already exists.
- A conflict identifies the affected destination and allows the member to retry that
  file with an explicit overwrite choice when overwrite remains authorized.
- A destination that changes between conflict inspection and commit is detected or
  fenced so an explicit choice cannot unknowingly replace a different concurrent
  result.
- The final destination becomes visible only after complete-byte, size, and integrity
  verification succeeds.
- A failed, cancelled, expired, or fenced attempt leaves no partial destination or
  temporary file visible in the file browser.

### REQ-4. Authorization, containment, and current Runtime authority

Every upload must preserve the existing Agent Workspace permission and trust
boundaries from browser admission through final Runtime commit.

**Acceptance criteria**

- The server authenticates the requester and authorizes access to the exact Workspace
  and Agent before accepting or exposing upload state.
- The destination is resolved from current Runner-reported Agent Workspace evidence and
  cannot escape that root through absolute-path substitution, traversal, symlink, or
  stale Provider configuration.
- Commit is fenced to the admitted Runtime, current Runner generation, and exact upload
  attempt; stale or duplicate attempts cannot publish a destination.
- The browser receives only a short-lived, write-only upload capability bound to the
  exact requester-authorized operation, object target, required headers, and expiry. It
  receives no storage credential, list authority, arbitrary key authority, or read
  capability.
- The Runner may receive only a short-lived, read-only object download capability bound
  to the exact verified upload source, delivery attempt, and deadline. It receives no
  long-lived object-storage credential, writable namespace authority, or browser-facing
  upload authority.
- Browser upload and Runtime download use the configured public endpoint, but neither
  makes the private bucket or object public.
- The object download path is Platform transfer infrastructure. Supporting it must not
  grant the Runtime general customer-network access or bypass the selected Runtime
  network policy.
- Another requester, Workspace, Agent, Runtime, or generation cannot inspect, cancel,
  finalize, retry, or consume the attempt.

### REQ-5. Bounded transfer and body isolation

The browser-to-Runtime path must remain bounded and must not make coordination or
application history proportional to complete file bodies.

**Acceptance criteria**

- Files above the configured Runtime transfer maximum fail before Runtime destination
  commit with a clear size-limit result.
- Browser ingress and Runtime delivery transfer file bytes directly with object
  storage. Integrity verification, finalization, and cleanup use bounded metadata,
  checksum, or object-native operations rather than a complete body in Main Web, the
  public API, Runtime Control, PostgreSQL, Redis, control events, logs, or durable
  history.
- The browser uploads to an operation-scoped ingress target through a presigned request.
  Authenticated finalization reauthorizes the requester and verifies exact object size,
  checksum, and source identity before Runtime delivery becomes eligible.
- The Runtime downloads the verified immutable source directly from the configured
  S3-compatible download endpoint. Runtime Control does not relay those file bytes
  through the Runner transfer gRPC stream.
- Per-Runtime and deployment-wide admission, concurrency, deadline, and lifetime limits
  continue to protect object storage, Runtime Control, the Runner, and unrelated
  control traffic.
- Transport-owned temporary bytes and bounded attempt metadata are deleted or expire
  after success, cancellation, failure, or timeout through an observable bounded
  cleanup path.
- Loss of optional Redis coordination does not create a false success, revive an old
  attempt, or prevent a later new upload from starting normally.

### REQ-6. Existing behavior and verification remain authoritative

Workspace upload must extend the current file browser without weakening or replacing
existing file and Runtime contracts.

**Acceptance criteria**

- Existing Workspace listing, preview, download, move, rename, delete, Project, and
  lifecycle behavior remains unchanged outside the new upload controls and refresh.
- Existing typed Runtime Transfer integrity, generation, admission, cancellation,
  atomic commit, and cleanup guarantees remain regression gates even though Workspace
  upload replaces the inner gRPC byte stream with the S3-compatible download path.
- Existing Agent profile-image upload keeps its current public behavior. Workspace
  Upload may reuse its presigned ticket and CORS patterns but must not reuse its
  complete-body server finalize behavior.
- The new public API surface is represented in OpenAPI and generated clients; the Web
  application does not introduce a parallel handwritten backend contract.
- Product behavior is covered E2E-first for success, conflict and explicit overwrite,
  cancellation, retry after failure, mixed multi-file outcomes, authorization, path
  containment, and Runtime generation loss.
- User-facing text and service errors are in English and localized by the Web client
  where the existing UI localization boundary applies.

## Fixed Constraints

- Runner remains untrusted. Runtime Control owns upload-source authorization and issues
  only an attempt-bound, expiring read capability; the Runtime never receives durable
  S3 credentials or writable object authority.
- The browser receives one attempt-bound, expiring write capability and never receives
  storage credentials, arbitrary object identity authority, or a reusable upload
  namespace.
- File bytes do not travel through Runner Control operations, Runtime coordination
  events, Main Web, the public API application body path, Runtime Control application
  memory, Redis values, PostgreSQL, logs, or durable Agent history.
- Workspace paths derive only from current Runner-reported Agent Workspace evidence.
- Runtime Transfer's existing one-hour logical lifetime, integrity contract, generation
  fencing, bounded admission, cancellation, atomic commit, and retry-from-zero boundary
  remain authoritative around the direct object download.
- Workspace upload requires the configured public S3-compatible endpoint and remains
  available in every supported Runtime network mode. That endpoint is reachable only
  as Platform transfer infrastructure and does not grant general customer-network
  authority or make the bucket public.
- The public endpoint CORS policy permits the Main Web origin and only the methods and
  signed headers required by the upload ticket.
- There is no fallback that relays Workspace upload bytes through Main Web, the public
  API, or Runtime Control when direct object-storage ingress or Runtime download is
  unavailable.
- Redis is optional coordination and cannot be required for correctness or recovery.
- No legacy inline-binary or mixed-version fallback is added.

## Open Assumptions

- Browser-level offset resume and cross-reload continuation are not required; retry
  begins a new file attempt from byte zero.
- Numeric file-size, concurrency, and buffer defaults remain reversible operational
  configuration within the existing Runtime transfer ceilings.

## Confirmation

The unchanged product behavior was confirmed by the requester for `upload-260917/REQ`
on 2026-09-17. Before that snapshot was implemented, the requester required Runtime
delivery to use the existing presigned S3-compatible download path and confirmed the
public endpoint plus exact-attempt claim contract. The requester then identified the
existing Agent profile-image presigned upload path as the ingress precedent and
directed the Workspace upload design to reuse that pattern. This snapshot preserves
the distinct `Uploading` and `Moving to Agent Runtime` phases and supersedes both
earlier transport boundaries.
