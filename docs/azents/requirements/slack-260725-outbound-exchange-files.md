---
title: "External Channel Exchange File Publication Requirements"
created: 2026-07-25
updated: 2026-07-25
implemented: 2026-07-25
tags: [slack, external-channel, exchange-file, files]
document_role: primary
document_type: requirements
snapshot_id: slack-260725
---

# External Channel Exchange File Publication Requirements

- Snapshot: `slack-260725`
- Document reference: `slack-260725/REQ`

## Problem

An Agent can explicitly publish Runtime files in an External Channel reply, but it
cannot publish an authorized `exchange://` file directly. The current Slack external
upload completion also receives a provider rejection after file bytes have uploaded,
preventing a requested file reply from appearing in the linked Slack thread.

## Primary Actor

An authorized Slack channel participant collaborating with an Agent that has a file
result represented by an Exchange file or a Runtime file.

## Primary Scenario

The Agent completes work for a linked Slack conversation and invokes `channel_action`
with explanatory text and one or more file references. Authorized `exchange://` files
and absolute Runtime files are published as attachments in the same Slack thread, and
the participant sees the completed reply.

## Supporting Scenarios

- An Agent attaches both a Runtime file and an Exchange file in one reply.
- An Exchange file becomes unavailable, expires, or is no longer authorized after
  preflight; the reply fails clearly without publishing a misleading success.
- The Agent supplies a relative path or an unsupported URI scheme and receives a clear
  Tool error before a provider call.
- A Slack completion request includes multiple ordered files and reply text.

## Goals

- Allow explicit External Channel replies to use authorized Exchange files directly.
- Preserve existing absolute Runtime-path publication behavior.
- Describe the accepted source forms in the `channel_action` Tool contract.
- Complete Slack file uploads using a provider-compatible request representation.
- Keep file authorization, configured limits, and commit-before-delivery behavior
  intact.

## Non-Goals

- Supporting `artifact://`, `azents://`, HTTP(S), relative paths, or arbitrary URI
  schemes as External Channel outbound files.
- Creating a new upload-only Tool or automatic outbound relay.
- Changing Slack inbound-file materialization.
- Persisting file bytes, credentials, or Slack upload URLs in a Channel action.
- Retrying ambiguous or failed provider uploads automatically.

## Requirements

### REQ-1. Explicit supported source forms

`channel_action.files` must accept absolute Runtime paths and authorized `exchange://`
file-location URIs, and its Tool description must state those forms and rejected forms.

**Acceptance criteria**

- An absolute Runtime path remains valid.
- An `exchange://` URI valid for the current execution authority is valid.
- Relative paths, `artifact://`, and `azents://` are rejected before provider mutation.
- A file-bearing action still requires explanatory message text and accepts at most the
  existing configured count.

### REQ-2. Execution-scoped Exchange authorization

An Exchange file used for outbound publication must be authorized by the current
canonical Session and run execution authority before commit and again immediately
before its bytes are sent.

**Acceptance criteria**

- Authorization never derives from requester, sender, uploader, owner, or viewer
  identity.
- A file outside the current Agent/root-Session scope is rejected.
- Expired, unavailable, or removed files are rejected.
- A post-commit authorization or availability failure produces a failed delivery and
  does not call Slack completion.

### REQ-3. Uniform outbound limits and metadata

Runtime and Exchange sources must both obey the existing outbound per-file and aggregate
limits, and durable actions must retain only bounded source metadata.

**Acceptance criteria**

- Exchange file metadata and actual bytes are checked against the declared size.
- Per-file and aggregate limits apply before action commit.
- No file body, bearer credential, or provider upload URL is persisted.
- The existing Runtime manifest remains readable for already-committed Runtime actions.

### REQ-4. Slack file completion compatibility

Slack file completion must send ordered file IDs, titles, thread target, and explanatory
text in a request representation accepted by Slack's external upload flow.

**Acceptance criteria**

- File bytes upload before exactly one completion request.
- Completion carries the ordered `files` collection, channel, root thread timestamp,
  and initial comment.
- The completion request encoding and body are covered by a regression test.
- A Slack rejection remains a controlled failed delivery with a bounded provider error.

## Fixed Constraints

- External Channel publication remains an explicit `channel_action` boundary.
- Canonical Session resource authority is the only execution authorization authority.
- Delivery remains commit-before-provider-call and at most once; failed or ambiguous
  uploads are not replayed automatically.
- Runtime absolute-path behavior remains supported.
- Git-tracked implementation and documentation are in English.

## Open Assumptions

- Exchange file resolution remains whole-file bounded by the configured outbound limits
  until the Exchange storage interface offers a streaming read contract.

## Confirmation

Confirmed by the requester on 2026-07-25 with the requests to support Exchange file
paths in `channel_action.files`, document supported paths, and fix the observed Slack
file-delivery failure before ADR and design decisions began.
