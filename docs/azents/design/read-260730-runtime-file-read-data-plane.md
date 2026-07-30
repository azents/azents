---
title: "Runtime File Read Data Plane Design"
created: 2026-07-30
updated: 2026-07-30
implemented: 2026-07-30
tags: [runtime, files, transfer, engine, api]
document_role: primary
document_type: design
snapshot_id: read-260730
---

# Runtime File Read Data Plane Design

- Snapshot: `read-260730`
- Requirements: [read-260730/REQ](../requirements/read-260730-runtime-file-read-data-plane.md)
- ADR: [read-260730/ADR](../adr/read-260730-runtime-file-read-data-plane.md)

## Design

### Bounded text path

Add `file.read_text` as a typed Runner operation. Its request accepts a path, byte cursor, maximum byte count, and text encoding (default UTF-8). Runner uses a buffered file read, strictly decodes the returned slice with that encoding, and emits direct text or a stable decode error in the final result. The Engine `read` tool requests this operation and presents the returned text; it no longer calls `FileStorage.get()`.

The maximum returned text payload is independently bounded below the Runner Control message limit. The cursor is byte-based and is returned to the caller so the next read does not require Worker-side reconstruction of earlier file contents.

### Binary object path

Extract a reusable Runtime-to-server object-consumption service from the existing managed publication transfer. The service admits and dispatches a Runtime upload, waits for a verified temporary transfer object, claims a consumer lease, invokes a trusted callback with its opaque handle and verified manifest, then acknowledges and settles on success or abandons and cancels on failure.

`read_image` provides a callback that resolves the opaque object inside trusted server code, downloads the bounded image body from S3-compatible storage, and invokes existing `ModelFileService.create()` normalization. It emits only the resulting `FilePart` reference.

The Workspace API uses the same consumer service: text preview uses `file.read_text`; complete downloads claim a verified transfer object and materialize it only in the HTTP response adapter. The initial implementation may retain an application `bytes` response adapter where the REST endpoint contract requires it; it must not use Runner Control file events.

## Failure handling

- Invalid paths, file absence, invalid UTF-8, range violations, and Runner unavailability return stable operation errors.
- Binary transfer failure, timeout, or cancellation does not invoke the consumer callback.
- Consumer transformation failure abandons the claim and settles the transfer as failed; no ModelFile is retained.
- ModelFile unavailable content remains a bounded transcript placeholder under the existing lowerer behavior.

## Security

The Runner never receives S3/RustFS authority. Opaque transfer object handles are resolved only by trusted server services. Existing Agent/Session authority, Runtime generation fencing, transfer leases, and object cleanup remain the source of truth.

## Test Strategy

- Unit tests cover text cursor reads, UTF-8 validation, protocol payload conversion, and no-Base64 event behavior.
- Unit tests cover binary transfer consumer settlement, callback failures, and ModelFile admission failures.
- Integration tests cover Runner transfer upload to an object-backed fake and image FilePart production.
- E2E coverage extends the Runtime workspace scenario with paged text read and a Runtime image larger than the ordinary Control read threshold; CI must pass required unit, type, build, and integration checks before merge.

## Traceability

| Requirement | ADR | Mechanism |
| --- | --- | --- |
| REQ-1 | ADR-D1 | `file.read_text`, byte cursor, bounded direct text result |
| REQ-2 | ADR-D2 | Runtime-to-server object consumer and transfer lease |
| REQ-3 | ADR-D3 | verified object image normalization into ModelFile |
| REQ-4 | ADR-D1, ADR-D2 | Workspace preview and download consumer paths |
