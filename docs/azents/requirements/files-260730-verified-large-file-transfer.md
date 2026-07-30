---
title: "Verified Large External File Transfer Requirements"
created: 2026-07-30
updated: 2026-07-30
tags: [external-channel, files, runtime, transfer]
document_role: primary
document_type: requirements
snapshot_id: files-260730
implemented: 2026-07-30
---

# Verified Large External File Transfer Requirements

- Snapshot: `files-260730`
- Document reference: `files-260730/REQ`

## Problem

External Channel attachments can be large, but the current download flow permits a
transfer trigger without requiring the Agent to name the observed size and can reject
otherwise valid work before streaming capacity is available. This makes a selected
attachment's cost and expected result unclear and turns temporary concurrency pressure
into a user-visible failure.

## Primary Actor

An Agent handling a message from an active External Channel conversation.

## Primary Scenario

The Agent sees an attachment's displayed size, explicitly selects that exact size in a
single-file download request, and receives the file at the requested Runtime path after
Azents verifies that the provider metadata, HTTP response, and received bytes describe
the same file. When other files are transferring, the request waits fairly and completes
without being rejected merely because transfer workers are busy.

## Supporting Scenarios

- A provider omits a size or returns a response whose declared or received size differs
  from the attachment selected by the Agent.
- Multiple Runtime file transfers are active at once, including files with very different
  sizes.
- A queued or active transfer is cancelled, expires, or fails verification.

## Goals

- Allow one explicitly selected External Channel attachment up to 500 MiB to download to
  the Runtime.
- Make the selected attachment size visible and part of the explicit download request.
- Fail closed before Runtime destination commit when any size evidence differs.
- Serve concurrent file transfers fairly at chunk granularity rather than rejecting a
  request because workers are occupied.

## Non-Goals

- Changing outbound External Channel publication limits or behavior.
- Giving the Runtime direct provider credentials, provider URLs, or object-store
  authority.
- Resuming an interrupted provider download from an arbitrary byte offset.
- Automatically downloading an attachment whose observed size is absent or ambiguous.

## Requirements

### REQ-1. One verified inbound attachment may be up to 500 MiB

Azents must allow a single explicitly requested External Channel attachment with an
observed size from zero through 500 MiB inclusive to download to the selected Runtime
path.

**Acceptance criteria**

- A 500 MiB attachment with consistent size evidence is eligible for download.
- An attachment whose selected, provider-reported, response-declared, or received size
  exceeds 500 MiB fails before Runtime destination commit.
- No aggregate active-transfer byte limit rejects an otherwise eligible attachment.

### REQ-2. The Agent must explicitly select the observed attachment size

Agent-visible attachment information must show a concrete byte size for a downloadable
attachment. The download request must include the exact observed byte size.

**Acceptance criteria**

- A download request without an expected size is invalid.
- An attachment without a valid observed size is not downloadable.
- A request whose expected size differs from the current provider metadata fails before
  the provider body is read.

### REQ-3. All available size evidence must agree before commit

Azents must treat the provider metadata size, HTTP `Content-Length`, and received body
size as one integrity contract for an inbound attachment.

**Acceptance criteria**

- A missing, invalid, or mismatched `Content-Length` fails the request.
- A body shorter or longer than the selected size fails and leaves no Runtime destination
  commit.
- A successful transfer reports the verified received byte count.

### REQ-4. Concurrent files receive chunk-granular fair service

When multiple file transfers compete for Runtime delivery capacity, Azents must schedule
one file's next chunk after another eligible file's next chunk in round-robin order.

**Acceptance criteria**

- A busy transfer worker causes a later eligible file to wait rather than receive an
  immediate capacity rejection.
- A multi-chunk file cannot monopolize all delivery capacity while another eligible file
  is waiting.
- FIFO order is preserved for chunks of the same file.
- Cancelled, expired, failed, or completed files are removed from fair scheduling.

### REQ-5. Failure remains controlled and confidential

Expected validation, queueing, and Runtime Control transport failures must produce
controlled tool failures without exposing provider credentials, provider URLs, gRPC
implementation details, or object-store authority.

**Acceptance criteria**

- A coordinator `RESOURCE_EXHAUSTED` or transport error never reaches the Agent as a raw
  `AioRpcError`.
- Failed transfer cleanup leaves no partial Runtime destination commit.
- Server logs retain diagnostic context without placing it in the tool result.

## Fixed Constraints

- The transfer remains a trusted server-to-Runtime flow through verified object-store
  staging; the Runtime receives no direct provider or S3 authority.
- One download request handles exactly one attachment and one absolute Runtime path.
- The displayed and requested size is measured in bytes.
- 500 MiB means 524,288,000 bytes.
- An HTTP response without `Content-Length` is not eligible for this download flow.
- Fairness applies to inbound Runtime-delivery chunks, not to complete-file buffering.

## Open Assumptions

- Providers continue to expose a current attachment metadata size before a body is
  downloaded.
- The existing transfer deadline remains sufficient for a 500 MiB streamed transfer in a
  supported deployment; timeout tuning is operational configuration, not a second file
  size policy.

## Confirmation

Confirmed by the requester on 2026-07-30 before ADR and design decisions began. The
requester directed autonomous completion of the remaining design details, implementation,
living-spec updates, one pull request, and CI verification.
