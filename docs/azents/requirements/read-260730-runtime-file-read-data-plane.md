---
title: "Runtime File Read Data Plane Requirements"
created: 2026-07-30
updated: 2026-07-30
implemented: 2026-07-30
tags: [runtime, files, transfer, transport]
document_role: primary
document_type: requirements
snapshot_id: read-260730
---

# Runtime File Read Data Plane Requirements

- Snapshot: `read-260730`
- Document reference: `read-260730/REQ`

## Problem

Runtime text and binary file reads still use the ordinary Runner Control operation path. The Runner encodes file bytes as Base64 control events and the Worker reconstructs a complete `bytes` value. This retains a control-plane body path after the Runtime File Transfer capability moved complete cross-boundary files to a dedicated bounded data plane.

## Primary Actor

An Agent reading a text or image file from its Runtime workspace while serving a user request.

## Primary Scenario

An Agent reads a large UTF-8 text file in pages and reads an image from its Runtime workspace. Text reaches the Agent as bounded UTF-8 content without Base64 file events. Image bytes cross the Runtime boundary through the verified Runtime Transfer data plane, are stored and normalized as model input, and do not occupy the Runner Control operation event stream.

## Goals

- Provide a bounded Runtime text-read operation that returns UTF-8 text without Base64 encoding.
- Move Runtime binary-file consumers to the existing verified Runtime Transfer and internal object-storage path.
- Preserve Runtime authorization, generation fencing, cancellation, and file-content confidentiality.
- Keep model text and image behavior observable and provide concrete failures.

## Non-Goals

- Giving Runners direct RustFS/S3 credentials, object URLs, or object identities.
- Moving arbitrary process output, patch payloads, or shell output to object storage.
- Changing Runtime file-write, edit, or patch behavior in this snapshot.
- Retaining the legacy Base64 `file.read` fallback for migrated consumers.

## Requirements

### REQ-1. Bounded Runtime text reads

The Agent `read` tool must request a bounded UTF-8 range from the Runtime and receive text directly rather than a Base64 file event.

**Acceptance criteria**

- The Runner decodes the requested bounded range with an explicit caller encoding, defaulting to UTF-8.
- Invalid byte sequences return a deterministic decode error; binary data is never replacement-decoded.
- The Runner Control operation event contains text, never Base64 file content, for the text-read operation.
- The tool reports a deterministic invalid-UTF-8 or unavailable-file failure.
- Repeated reads can advance through a file without Worker-side reconstruction of an earlier complete file body.

### REQ-2. Runtime binary reads through the transfer data plane

A Runtime image selected by `read_image` must cross the Runtime boundary through the verified Runtime-to-server transfer capability and a temporary internal object.

**Acceptance criteria**

- Runner Control operation requests and events do not carry the selected image body or Base64 image body.
- The Runner receives no object-store credential, object key, URL, or storage topology.
- The image consumer receives a verified object only after transfer completion and integrity validation.
- A failed, cancelled, unavailable, or oversized transfer does not create model input.

### REQ-3. Model image admission

The image read path must preserve the existing model-input normalization and durable `ModelFile` lifecycle after the binary transfer completes.

**Acceptance criteria**

- A successful image remains available to the next model request as an image `FilePart`.
- Canonical transcript events and browser projections do not contain raw image bytes or Base64 payloads.
- Model input failures identify transfer, image validation, or model-file admission as applicable.

### REQ-4. Current product surfaces

The Runtime Workspace API must use bounded direct text reads for text preview and the transfer object path for complete binary downloads.

**Acceptance criteria**

- Text preview does not request an unbounded `file.read` body.
- A complete workspace file download does not use Runner Control Base64 file events.
- Existing workspace authorization remains enforced before Runtime access.

## Fixed Constraints

- Runtime Control remains the trusted boundary for S3/RustFS access and Runner data streams.
- Runtime transfer content stays temporary and is settled/cleaned using the existing transfer lifecycle.
- The implementation is delivered as one PR with updated current-behavior specifications and CI passing.

## Requester Confirmation

The requester explicitly approved implementation of this scope and requested one PR with CI passing on July 30, 2026.
