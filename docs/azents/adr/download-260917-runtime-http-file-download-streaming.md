---
title: "Runtime HTTP File Download Streaming Decisions"
created: 2026-09-17
tags: [runtime, files, http, transport]
document_role: primary
document_type: adr
snapshot_id: download-260917
---

# Runtime HTTP File Download Streaming Decisions

- Snapshot: `download-260917`
- Requirements: [download-260917/REQ](../requirements/download-260917-runtime-http-file-download-streaming.md)
- Document reference: `download-260917/ADR`

## Decision Summary

- `download-260917/ADR-D1` — Return a response-scoped bounded stream handle instead of
  a complete `bytes` value from the Workspace and Exchange download services.
- `download-260917/ADR-D2` — Keep the Workspace Runtime transfer consumer claim alive
  for the complete HTTP body lifetime and settle it only from the body terminal outcome.
- `download-260917/ADR-D3` — Stream Exchange objects from their existing authorized
  object-storage source without routing them through Runtime Transfer or creating a
  new durable copy.
- `download-260917/ADR-D4` — Preserve the existing public routes and headers while
  leaving `RuntimeRunnerTransfer` and persistent `RuntimeStreamSession` unchanged.
- `download-260917/ADR-D5` — Treat file bytes over the persistent Runtime Stream
  Session as a separate follow-up snapshot after this HTTP boundary is implemented
  and verified.

## Context

The current Workspace HTTP route already obtains a verified Runtime-to-server transfer
object, but its response adapter reads that object into `bytes` before constructing a
`StreamingResponse`. The Exchange route similarly reads its complete object before
constructing the response. The final HTTP boundary therefore defeats the bounded
streaming behavior of the lower-level sources.

The existing Runtime transfer contract has a consumer-lease and settlement lifecycle.
A transfer object must not be acknowledged and deleted while an HTTP response still
may need to read it. Conversely, an HTTP client disconnect must not be mistaken for a
successful complete download. Exchange files have a different source authority: their
requester permission and expiration are checked by ExchangeFileService, and the object
is already owned by the server-side product storage.

The persistent Runtime Stream Session currently carries HTTP and WebSocket application
streams with Web-specific service/port authority. It is the planned future transport
boundary for a file-stream capability, but adding file frames now would mix the
follow-up B goal with the independently useful A goal and would introduce a second
file authority model before the HTTP lifecycle is fixed.

## `download-260917/ADR-D1`: Use a response-scoped bounded stream handle

**Authority:** `download-260917/REQ-1`, `REQ-2`, `REQ-3`.

Workspace and Exchange download services return response metadata together with a
single-use, bounded asynchronous body handle. The handle owns source opening,
iteration, cancellation, and close-on-exit. The API adapter passes that body to the
existing HTTP streaming response mechanism and does not materialize the complete file
before returning.

The handle is not a replayable resource and does not expose storage identity,
credentials, provider URLs, or transfer state to the caller. It reports normal EOF
separately from cancellation, source failure, deadline expiry, and integrity failure.

**Rejected alternatives**

- Returning `bytes` and wrapping it in `BytesIO` preserves the current memory spike
  and does not satisfy the primary outcome.
- Returning a raw storage response object leaks source ownership and makes close and
  authority behavior dependent on the HTTP framework.
- Exposing a replayable iterator or cache adds a second retention and replay contract
  that is outside this snapshot.

**Consequences**

- The API service and response adapter must share a clear ownership boundary for body
  close and cancellation.
- Tests must exercise the body after the service method has returned, not only inspect
  an eagerly prepared value.
- The response path can apply backpressure without a complete in-memory copy.

## `download-260917/ADR-D2`: Bind Workspace transfer settlement to HTTP body completion

**Authority:** `download-260917/REQ-1`, `REQ-3`, `REQ-4`.

Workspace keeps the existing typed Runtime-to-server transfer, verified temporary
object, consumer lease, and one-hour logical lifetime. The transfer service exposes a
response-scoped consumer stream only after the Runtime upload is verified and the
consumer claim is established. The claim is renewed while the HTTP body is being
consumed.

Normal EOF is the only successful consumer outcome. The expected byte count must have
been yielded exactly, the underlying object stream must close normally, and then the
consumer is acknowledged and the transfer is settled successfully. Any cancellation,
client disconnect, deadline, source read error, integrity mismatch, or other
non-EOF exit abandons or cancels the claim through the existing bounded cleanup path.
The same transfer attempt is never implicitly replayed.

The HTTP response adapter does not acknowledge, settle, or delete the transfer object
merely because Runtime-to-server upload completed. It owns the final body-lifecycle
signal and closes the stream on every exit path.

**Rejected alternatives**

- Settling immediately after Runtime upload and then reading the object later can
  delete or expire the only verified source before the client has consumed it.
- Treating a client disconnect as success creates false complete-download evidence and
  can hide truncated responses.
- Retrying a partially delivered HTTP response with the same attempt creates unsafe
  duplicate consumption and ambiguous byte accounting.
- Copying the object into a durable Exchange file before responding changes Workspace
  download retention and product ownership merely to avoid lease coordination.

**Consequences**

- A slow client retains one bounded consumer claim for the response duration, bounded
  by the existing transfer lifetime and response deadline.
- The transfer consumer lease renewal and HTTP body producer must be cancellation-safe
  and must not leave a task running after the response closes.
- A response can be visibly started before a later source failure; the failure remains
  an unsuccessful transfer outcome even when HTTP status headers were already sent.

## `download-260917/ADR-D3`: Keep Exchange source authority separate

**Authority:** `download-260917/REQ-2`, `REQ-4`.

Exchange download performs the existing requester authorization and expiration checks
before opening a bounded object-storage iterator. It streams the exact stored object
through the response-scoped handle and closes the iterator on normal EOF, cancellation,
disconnect, or error. It does not create a Runtime transfer attempt, consume a Runtime
claim, or create a new product object.

The commonality between Workspace and Exchange is the response-body lifecycle contract,
not a shared authority or retention implementation. Workspace remains Runtime-fenced;
Exchange remains ExchangeFileService-fenced.

**Rejected alternatives**

- Routing Exchange through Runtime Transfer adds an unnecessary Runtime dependency and
  changes a server-owned product source into a temporary transport object.
- Reusing Workspace's consumer-lease model for Exchange obscures the product source's
  existing retention and permission authority.
- Replacing Exchange metadata checks with storage-only access would permit expired or
  unauthorized product files to be streamed.

**Consequences**

- The two source adapters need separate failure mapping while satisfying one HTTP body
  contract.
- Exchange continues to use its existing object retention and metadata semantics.
- A future common source abstraction must not erase the authority distinction.

## `download-260917/ADR-D4`: Preserve public and protocol boundaries

**Authority:** `download-260917/REQ-4`, `REQ-5`.

The existing Workspace and Exchange route paths, response status behavior before body
streaming, media types, and `Content-Disposition` filename behavior remain unchanged.
The typed `RuntimeRunnerTransfer` protocol, transfer coordinator state and cleanup
policy, Runner file commit contract, and persistent `RuntimeStreamSession` protocol
are not modified by A.

No compatibility alias, new protobuf message, file stream mode, capability flag, or
fallback between typed transfer and persistent session is introduced.

**Rejected alternatives**

- Changing public routes or adding a second download route expands the product surface
  without a requirement.
- Adding a protocol flag for an optional streaming mode creates mixed behavior and a
  rollout compatibility surface that A does not need.
- Moving only generated names or transport symbols does not address the HTTP memory
  boundary.

**Consequences**

- A can be deployed and rolled back independently of the later file-stream protocol.
- Existing Runtime Transfer and Runtime Stream Session tests remain regression gates.
- The HTTP response change must be verified without relying on a protocol cutover.

## `download-260917/ADR-D5`: Defer persistent-session file bytes to B

**Authority:** `download-260917/REQ-1`, `REQ-4`, `REQ-5`; requester scope confirmation
on 2026-09-17.

The next goal is a new development snapshot that may add file logical streams to the
persistent Runtime Stream Session. That snapshot must separately decide file-stream
authority, framing, flow-control interaction, attempt/claim lifetime, object staging,
resume policy, and mixed-version rollout. A does not pre-decide those choices and does
not add file-specific messages or state.

**Rejected alternatives**

- Adding a provisional file mode now couples two independently verifiable rollouts and
  makes it difficult to tell whether HTTP lifecycle fixes or protocol changes caused a
  regression.
- Treating the existing HTTP/WebSocket `DATA` frames as an implicit file protocol
  leaves file identity, integrity, and cleanup semantics unspecified.

**Consequences**

- B can reuse the response-boundary lessons from A without requiring a revert.
- The current persistent session remains Web-specific at the application adapter
  boundary until B is designed and approved.

## Risks and Required Evidence

- Framework cancellation and disconnect behavior may differ between test and deployed
  servers; integration tests must prove that the body producer closes and settles on
  every exit path.
- Holding a Workspace consumer lease for a slow HTTP client consumes bounded volatile
  capacity; metrics and deadline behavior must remain visible without logging file
  content or storage identity.
- A response failure after headers are sent cannot change the HTTP status; the Runtime
  transfer outcome and cleanup evidence remain the authoritative operator signal.

Required evidence includes bounded multi-chunk and zero-byte responses, exact byte
counts, source read failure, cancellation/disconnect, lease renewal, normal EOF
settlement, no premature cleanup, exact filename/media-type headers, and unchanged
Runtime Transfer, Runtime Stream Session, and External Channel file-transfer tests.

## Decision Ownership

The requester confirmed the A-first/B-next scope on 2026-09-17. The Agent selected the
response-scoped handle, Workspace lease lifetime, separate Exchange authority, and
protocol-preserving boundaries as technical decisions required to implement the
confirmed Requirements.
