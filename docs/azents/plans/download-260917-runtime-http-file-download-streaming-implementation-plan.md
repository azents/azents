---
title: "Runtime HTTP File Download Streaming Implementation Plan"
created: 2026-09-17
tags: [runtime, files, http, transfer, api, testing]
---
# Runtime HTTP File Download Streaming Implementation Plan

## Authority and Scope

- Requirements:
  [Runtime HTTP File Download Streaming Requirements](../requirements/download-260917-runtime-http-file-download-streaming.md)
  (`download-260917/REQ-1` through `REQ-5`).
- Decisions:
  [Runtime HTTP File Download Streaming ADR](../adr/download-260917-runtime-http-file-download-streaming.md)
  (`download-260917/ADR-D1` through `ADR-D5`).
- Approved Design:
  [Runtime HTTP File Download Streaming Design](../design/download-260917-runtime-http-file-download-streaming.md),
  revision `3`, mechanisms `M1` through `M7`.
- Current Specs:
  [Agent Runtime Control](../spec/flow/agent-runtime-control.md) and
  [File Exchange and Storage](../spec/flow/file-exchange-storage.md).
- Design delta: None.

## Objective

Replace complete-body materialization in the existing Agent Workspace and Exchange
HTTP download routes with bounded, single-use response streams. Preserve the existing
Runtime File Transfer and Exchange authority boundaries, public routes and headers,
non-HTTP Exchange consumers, and persistent Runtime Stream Session protocol.

## Delivery Shape

Use one focused PR from `feat/runtime-http-download-streaming` to `main`. The Runtime
consumer lifecycle, response adapter, and both route cutovers form one atomic product
boundary: no intermediate branch should expose a response stream without terminal
cleanup or leave one route on an unverified lifecycle.

| Phase | Branch | Base | Deliverable | Dependencies |
| --- | --- | --- | --- | --- |
| 1 | `feat/runtime-http-download-streaming` | `main` | Response-scoped Runtime consumer, final-send-aware ASGI adapter, Workspace and Exchange route cutover, tests, validation, and Spec promotion | Approved revision 3 Design |

## Fixed Implementation Boundaries

- Exact verified EOF and successful return from the final ASGI body send are separate
  success evidence.
- That combined evidence is a sticky terminal commit point: later cancellation cannot
  switch Workspace settlement to abandonment.
- Workspace keeps the existing Runtime transfer admission, generation fencing,
  verified manifest, consumer lease, five-minute response deadline, one-hour logical
  lifetime, acknowledgement, settlement, and cleanup authority.
- Exchange keeps its existing requester authorization, expiration, metadata, object
  retention, and byte-returning internal consumers.
- Public routes, media types, UTF-8 filenames, pre-stream error mapping, and successful
  status behavior remain unchanged.
- No protobuf, database, Helm, Runtime Stream Session, compatibility alias, range,
  resume, replay, or live infrastructure change is included.

## Workstreams and Integration

1. Extract a reusable prepared Runtime consumer while preserving existing callback
   publication behavior.
2. Add source-specific single-use Workspace and Exchange response handles with bounded
   size and SHA-256 verification.
3. Add the shared ASGI response adapter with independent EOF/final-send evidence,
   sticky completion, explicit producer close, and exactly-once terminal action.
4. Replace the two public route byte wrappers while retaining non-HTTP Exchange APIs.
5. Add deterministic lifecycle, service, API, and public-path regression coverage.
6. Run integrated validation, update Living Specs, mark the snapshot implemented, and
   remove this plan and its phase plan before the PR is finalized.

## Removal and Absence Evidence

- Remove Workspace `_BytesCallback` complete-body materialization from the HTTP download
  path and prove `S3Service.download_bytes()` is not called there.
- Remove Workspace and Exchange route `io.BytesIO(...)` wrappers and prove the routes use
  the response-scoped adapter.
- Retain Exchange byte-returning methods for Agent input and External Channel delivery;
  their regression tests prove they remain authoritative outside HTTP.
- Prove no file message, mode, capability, alias, or fallback was added to
  `RuntimeStreamSession` or `RuntimeRunnerTransfer`.

## Validation Matrix

| Area | Required evidence |
| --- | --- |
| Runtime consumer | Preparation, renewal, exact completion, abandonment, lease loss, deadline, ambiguity recovery, and no replay |
| ASGI lifecycle | ASGI 2.3 and 2.4 normal send, EOF/final-send race, disconnect, send error, cancellation before and after commit, explicit close, exactly-once terminal action |
| Workspace | Zero-byte, multi-chunk, overflow, truncation, hash mismatch, unavailable source, cancellation, preserved metadata |
| Exchange | Authorization, expiry, missing object, bounded iteration, integrity, close on every exit, preserved byte consumers |
| API | Existing routes, filenames, media types, error mapping, streaming body behavior |
| Regression | Runtime File Transfer, Runtime Stream Session, Agent input, External Channel provider delivery |
| Quality | Ruff, format, `ty check --error-on-warning`, affected pytest suites, required public E2E |

## Reviewer and Checkpoints

`hardtack` is the independent reviewer for the complete integrated diff. Review inputs
are the confirmed Requirements, accepted ADR, approved Design revision 3, the phase
execution plan, removal evidence, and focused validation results.

The root agent owns implementation integration, all validation, review finding
resolution, Spec promotion, snapshot implementation dates, plan cleanup, PR creation,
and CI monitoring. No merge is performed without explicit requester approval.
