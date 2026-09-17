---
title: "Runtime HTTP File Download Streaming Requirements"
created: 2026-09-17
updated: 2026-09-17
tags: [runtime, files, http, transport]
document_role: primary
document_type: requirements
snapshot_id: download-260917
---

# Runtime HTTP File Download Streaming Requirements

- Snapshot: `download-260917`
- Document reference: `download-260917/REQ`

## Problem

The current HTTP download adapters for Agent Workspace and Exchange files materialize
an entire file as `bytes` before returning a `StreamingResponse`. This makes the
HTTP-serving process hold a complete copy of every downloaded file and prevents the
final response boundary from sharing the bounded streaming behavior already used by
the Runtime file-transfer path.

## Primary Actor

A signed-in Workspace member downloading a complete Agent Workspace or Exchange file
through the Main Web HTTP API.

## Primary Scenario

A requester selects a regular Agent Workspace file or an accessible Exchange file.
After the existing authorization and file validation succeed, the API begins returning
the file as an ordered bounded byte stream. The requester receives the same file
metadata and bytes as today without the API process assembling a second complete
in-memory body. If the requester cancels or disconnects before the end, the operation
is not reported as a successful complete download.

## Supporting Scenarios or Effects

- A zero-byte file produces a successful empty response without a special client path.
- A large file can be served while unrelated API requests continue to make progress.
- A missing, expired, unauthorized, changed, truncated, or unavailable source fails
  with the existing safe error behavior before or during streaming as appropriate.
- Runtime Workspace downloads retain the existing verified Runtime transfer integrity,
  generation, authorization, and cleanup guarantees while the HTTP body is consumed.
- Exchange downloads retain their existing requester authorization, expiration,
  content type, and filename behavior.
- The later file-stream extension of the persistent Runtime Stream Session can be
  developed as a separate follow-up snapshot without changing this stage's contract.

## Goals

- Remove complete-file buffering from the Main Web HTTP response boundary for Agent
  Workspace and Exchange file downloads.
- Keep response bytes bounded, ordered, and backpressured from the trusted source to
  the HTTP client.
- Preserve the existing routes, authorization checks, filename and media-type
  headers, overwrite and source validation behavior, and safe failure semantics.
- Keep Runtime file-transfer authority, integrity verification, attempt lifetime,
  consumer acknowledgement, cancellation, and cleanup authoritative for Workspace
  downloads.
- Make early client termination, deadline expiry, source failure, and successful EOF
  distinguishable at the download completion boundary.
- Keep file bytes out of PostgreSQL, Redis coordination state, logs, and durable
  request history.

## Non-Goals

- Moving file bytes into the persistent `RuntimeStreamSession` protocol or adding a
  file logical-stream mode; that is the next goal after this snapshot is implemented
  and verified.
- Changing the typed `RuntimeRunnerTransfer` RPC, transfer coordinator state model,
  one-hour logical transfer lifetime, object cleanup policy, or Runner file commit
  contract.
- Changing External Channel `download_external_file`, provider attachment discovery,
  provider download/upload protocols, or Runtime-to-provider publication.
- Adding range requests, resumable downloads, multi-consumer replay, caching, or a
  new public download route.
- Changing Exchange file retention, metadata, preview generation, or product
  publication semantics.
- Applying live Kubernetes or deployment changes as part of this snapshot.

## Requirements

### REQ-1. Bounded Agent Workspace HTTP response

The Agent Workspace download route must expose the authorized regular file as a
bounded asynchronous byte stream rather than an eagerly materialized complete body.

**Acceptance criteria**

- The existing Workspace download route and response metadata remain unchanged for a
  successful request.
- The API process does not create a complete `bytes` copy proportional to the file
  size before response streaming begins.
- The response yields ordered bytes until the verified source reaches EOF and does not
  yield bytes beyond the admitted source size.
- A zero-byte regular file completes successfully with an empty body.
- A source that cannot be verified, becomes unavailable, expires, is fenced, or is
  truncated does not produce a successful complete response.

### REQ-2. Bounded Exchange HTTP response

The Exchange file download route must stream the authorized original object directly
through a bounded asynchronous response body.

**Acceptance criteria**

- The existing Exchange download route, authorization behavior, media type, and
  `Content-Disposition` filename remain unchanged.
- The API process does not eagerly read the complete Exchange object into memory before
  returning the response.
- The response yields the exact stored object bytes in order and closes the source
  cleanly on EOF, cancellation, disconnect, or error.
- Missing, expired, unauthorized, and unavailable Exchange files retain their existing
  safe error behavior.

### REQ-3. Completion and cancellation semantics

The download boundary must distinguish server-observed complete response delivery from
early termination and must not claim a source as successfully consumed before the
response body has completed.

**Acceptance criteria**

- Successful completion is established only after the expected bytes reach verified EOF,
  the final ASGI body send returns successfully, and no earlier disconnect was observed.
- Completion does not claim that the client application persisted the response after the
  HTTP server accepted the final body send.
- Client cancellation, disconnect, deadline expiry, source read failure, or integrity
  mismatch before that completion point leaves the operation unsuccessful and invokes the
  existing bounded abandonment or cleanup path.
- Cancellation after that completion point does not switch a committed successful
  Workspace transfer back to abandonment.
- Early termination closes the underlying source promptly and does not leave an open
  response-body task or unbounded buffered data.
- A successful response cannot be followed by a second replay of the same transfer
  attempt through an implicit retry or fallback path.

### REQ-4. Existing authority and isolation remain authoritative

This snapshot must preserve the current authorization and isolation boundaries while
changing only the HTTP response consumption path.

**Acceptance criteria**

- Workspace requester authorization, Runtime readiness, current Runtime/Runner
  generation fencing, regular-file validation, and source-size verification run before
  bytes are exposed.
- Workspace transfer integrity and consumer-lease rules remain enforced for the full
  response lifetime.
- Exchange requester authorization and expiration checks run before bytes are exposed.
- No file body, storage credential, object key, provider URL, or transfer secret is
  persisted in PostgreSQL, Redis, logs, or durable Agent history.
- The typed Runtime File Transfer and persistent Runtime Stream Session contracts do
  not accept each other's messages or gain compatibility aliases as a side effect.

### REQ-5. Compatibility and verification

The change must preserve existing product behavior apart from removing complete-file
HTTP response buffering.

**Acceptance criteria**

- Existing Workspace and Exchange download API tests continue to pass with streaming
  body assertions.
- Tests cover zero-byte, bounded multi-chunk, source failure, cancellation or
  disconnect, and exact filename/media-type behavior.
- Existing Runtime File Transfer, Runtime Stream Session, and External Channel file
  transfer tests continue to pass without protocol or capability changes.
- The follow-up persistent-session file-stream work can depend on this snapshot
  without reverting the HTTP streaming boundary.

## Fixed Constraints

- Existing public routes and requester-visible successful response semantics remain.
- Existing typed Runtime File Transfer remains the authority for complete Workspace
  transfer across the Runtime boundary.
- Runtime transfer logical lifetime remains non-extendable and bounded by the existing
  one-hour policy.
- Runner remains untrusted and receives no storage authority.
- File bytes remain bounded and are never persisted in PostgreSQL, Redis coordination
  state, logs, or durable Agent history.
- A later B-stage file stream over the persistent Runtime Stream Session is a separate
  development snapshot and may not be smuggled into this stage.

## Open Assumptions

- The HTTP framework can consume an asynchronous iterable or equivalent response-body
  abstraction while propagating cancellation and disconnect to its producer.
- The trusted object-store adapter can expose bounded chunk iteration with deterministic
  close-on-EOF and close-on-cancellation behavior.
- The existing Runtime transfer consumer lease can remain active until the HTTP body
  producer confirms EOF or reports early termination.

## Confirmation

Scope confirmed by the requester on 2026-09-17: implement A first, then extend toward B
as a subsequent goal. B is intentionally deferred from this Requirements snapshot.

REQ-3 completion semantics clarified and confirmed by the requester on 2026-09-17:
completion means verified EOF plus successful return from the final ASGI body send without
an earlier observed disconnect, not proof that the client application persisted the body.
