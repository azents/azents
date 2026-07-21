---
title: "Attachment, Artifact, and FilePart lifecycle Historical Requirements Reconstruction"
created: 2026-06-01
implemented: 2026-06-01
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: file-260601
historical_reconstruction: true
migration_source: "docs/azents/adr/0046-file-media-resource-lifecycle.md"
---

# Attachment, Artifact, and FilePart lifecycle Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `file-260601`
- Source: `docs/azents/adr/file-260601-file-media-resource-lifecycle.md`
- Historical source date basis: `2026-06-01`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Recently image generation/input payloads were exposed as inline base64 in frontend wire payload and context inspector raw event, so redaction based on `sanitize_frontend_dict` was added. This hotfix protects browser memory and WebSocket payload, but root problem is that user-agent file delivery, agent/tool file outputs, and LLM input file parts are mixed in same payload space.

Initial assumption was: "images small enough to enter LLM input are probably fine to round-trip through RDB row and message payload." Codex and anomalyco/opencode research shows data URL/base64 patterns are common at model request layer, but guardrails such as resize, omit, strip, count-only telemetry also exist.

Azents crosses cloud runtime, RDB, broker, WebSocket, browser UI, context inspector, agent runtime, and MCP tool, so file/media concepts must be clearly separated.

This ADR separates these lifecycles:

- Attachment lifecycle: user-agent file delivery envelope. It contains Exchange URI and becomes basis for UI preview/download and runtime import/export. Actual exchange file may expire independently from event lifecycle.
- Artifact lifecycle: file output resource produced by agent/tool. Stored in ArtifactStore and accessed with `artifact://` URI. It is neither user-facing attachment nor LLM rich input FilePart. It is valid during creation run and next 2 completed runs, then expires/deletes.
- FilePart lifecycle: blob/content part that can directly enter LLM input. Same schema is used in input message and tool result output. It lowers to native rich content part such as `input_image`, `input_file` when provider request is built.
- ModelFile lifecycle: provider-neutral normalized blob identity referenced by FilePart. Stored in ModelFileStore. It is not original archive; it is normalized blob for model input budget management.

`exchange://` is backend-agnostic file exchange abstraction, not storage backend. Even if backend changes from S3 to filesystem, external scheme need not change. Exchange file has retention independent from event lifecycle and can expire later. Therefore load/download may fail even if Exchange URI remains in event/message.

`artifact://` is also backend-agnostic internal artifact address. Physical backend of ArtifactStore can be filesystem, S3-compatible object storage, or custom adapter. It may share physical backend with Exchange, but logical namespace, lifecycle, and access path are separate.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
