---
title: "Runtime File Read Data Plane"
created: 2026-07-30
tags: [architecture, runtime, files, transfer, grpc, s3]
document_role: primary
document_type: adr
snapshot_id: read-260730
---

# read-260730/ADR: Runtime File Read Data Plane

- Snapshot: `read-260730`

## Requirements

This ADR records decisions for [Runtime File Read Data Plane Requirements](../requirements/read-260730-runtime-file-read-data-plane.md) (`read-260730/REQ`).

## Context

The implemented `transfer-260725` snapshot deliberately left ordinary `file.read` on the Runner Control path. That operation returns Base64 file events and callers reconstruct complete bytes. Runtime text and image reads now need the same separation between bounded control content and complete binary data that transfer consumers use.

### read-260730/ADR-D1. Use a dedicated bounded `file.read_text` control operation

**Affected requirements:** `read-260730/REQ-1`, `REQ-4`.

Text is bounded semantic content, not a complete-file transfer. The Runner reads only the requested byte range and strictly decodes it with the caller-selected encoding (UTF-8 by default). It returns a typed text result through Runner Control and reports a stable decode error for invalid byte sequences. The operation has a strict maximum byte budget below Control message limits. It does not use `file_chunk` or Base64 fields.

**Rejected:** Sending text through the generic Base64 `file.read` event preserves the transport overhead and prevents true paging. Staging ordinary small text pages through S3 adds transfer lifecycle and object-store cost without improving safety.

### read-260730/ADR-D2. Use verified Runtime-to-server transfer objects for binary consumers

**Affected requirements:** `read-260730/REQ-2`, `REQ-3`, `REQ-4`.

A binary consumer admits a Runtime upload through the existing dedicated transfer RPC. Runtime Control writes the authenticated raw frames to a temporary S3-compatible object, verifies the manifest, and lets one trusted consumer claim the opaque object. The consumer settles or abandons the transfer after it has committed its product outcome.

**Rejected:** Reconstructing a complete binary body from Runner Control events would retain the unsafe Base64 control-plane path. A trusted API response adapter may materialize verified object bytes when its existing HTTP contract requires it; direct Runner access to S3 still contradicts the Runtime Transfer trust model.

### read-260730/ADR-D3. Keep image normalization as an explicit bounded transformation

**Affected requirements:** `read-260730/REQ-3`.

The image consumer may read the verified temporary object to normalize it into the existing JPEG-backed `ModelFile`. This is a byte-changing product transformation, not an unchanged-object publication. The consumer must enforce the model image size policy before ModelFile persistence and always settle or abandon its transfer object.

**Rejected:** Copying the transfer object directly into ModelFile would skip required image decode, EXIF orientation, alpha handling, and JPEG normalization.
