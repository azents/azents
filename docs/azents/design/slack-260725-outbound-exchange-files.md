---
title: "External Channel Exchange File Publication Design"
created: 2026-07-25
updated: 2026-07-25
implemented: 2026-07-25
tags: [slack, external-channel, exchange-file, runtime, delivery]
document_role: primary
document_type: design
snapshot_id: slack-260725
---

# External Channel Exchange File Publication Design

- Snapshot: `slack-260725`
- Document reference: `slack-260725/DESIGN`
- Requirements: [`slack-260725/REQ`](../requirements/slack-260725-outbound-exchange-files.md)
- ADR: [`slack-260725/ADR`](../adr/slack-260725-outbound-exchange-files.md)

## Overview

This focused change expands the explicit `channel_action.files` source boundary from
Runtime paths to two forms: absolute Runtime paths and authorized `exchange://` URIs.
It retains the commit-before-delivery ledger, configured limits, and no-retry behavior.
It also changes only Slack's external-upload completion call to the provider-compatible
form representation.

## Traceability

| Requirement | ADR decisions | Design mechanisms |
| --- | --- | --- |
| `slack-260725/REQ-1` | `slack-260725/ADR-D1` | Tool schema description, source classifier, fail-closed URI validation |
| `slack-260725/REQ-2` | `slack-260725/ADR-D1` | Canonical authority injection, preflight resolution, post-commit re-resolution |
| `slack-260725/REQ-3` | `slack-260725/ADR-D1` | Typed manifest source kind, shared limit checks, metadata/byte matching |
| `slack-260725/REQ-4` | `slack-260725/ADR-D2` | Form-capable Slack request helper and exact request-body regression test |

## Current Behavior and Gap

`ExternalChannelFileTransferService.prepare_outbound()` accepts only absolute Runtime
paths and records one manifest containing path, filename, media type, and expected size.
`ExternalChannelActionService` later streams that Runtime source after the action commits.

`ExchangeFileService.resolve_for_authority()` already resolves `exchange://` under
canonical execution authority and rechecks that authority after storage download. The
External Channel toolkit receives the same authority through `TurnContext`, but does not
currently pass it to outbound preflight or delivery.

`SlackConversationClient.post_file_message()` uses its JSON request path for
`files.completeUploadExternal`; observed Slack delivery rows show provider rejection at
that call after upload success.

## Source Contract and Manifest

Add a provider-neutral source kind to `ExternalChannelOutboundFileManifest`:

- `runtime`: `path` is an absolute Runtime path;
- `exchange`: `path` is an `exchange://` URI.

Existing persisted manifests without the source kind deserialize as `runtime`, preserving
already-committed Runtime delivery records. The manifest continues to contain only a
source reference, bounded filename, media type, and expected byte count.

The source classifier accepts an absolute POSIX path as `runtime`; it accepts an
`exchange://` URI only when its object key parser accepts the URI. It rejects relative
values and every other URI scheme with a direct Tool error. The `files` schema explains
these forms rather than describing every implementation detail.

## Preflight and Delivery

1. `ExternalChannelToolkit.update_context()` retains the current
   `SessionResourceAuthority` from `TurnContext`.
2. `channel_action` passes that authority to outbound preflight and the immediate
   post-commit delivery attempt.
3. Runtime preflight retains the existing stat/readability and limit checks.
4. Exchange preflight calls `resolve_for_authority()`, requires the returned metadata
   and actual byte length to agree, derives the manifest filename/media type from the
   resolved Exchange file, and applies the same per-file and aggregate limits.
5. The durable action commits its ordered manifests before any Slack mutation.
6. During an immediate delivery, a Runtime manifest streams checked ranges as before.
   An Exchange manifest resolves again through the same authority, verifies the committed
   size and bounded metadata, and yields fixed-size chunks from the bounded result.
7. A delivery resumed without the original execution authority cannot publish an Exchange
   source and terminalizes before provider completion. This is consistent with the
   existing no-replay file-source rule.

No user, requester, sender, uploader, creator, or viewer identity participates in these
checks.

## Slack Completion Request

Extend the internal Slack request helper with an optional form-data argument. It sends
an Authorization header for both JSON and form calls and selects exactly one body type.
The external upload acquisition remains JSON. Completion sends form fields:

- `files`: compact JSON serialization of ordered `{id, title}` objects;
- `channel_id`;
- `thread_ts`; and
- `initial_comment`.

The existing error classifier continues to map a Slack `ok: false` completion result to
a bounded confirmed provider rejection.

## Failure Handling

- Bad source syntax, missing authority, unauthorized Exchange content, expired content,
  invalid metadata, and configured size excess fail before action commit.
- A post-commit Exchange authorization, availability, metadata, or byte mismatch fails
  the delivery before Slack completion.
- Runtime stream failures retain their existing failed outcome.
- Upload transport ambiguity and completion transport ambiguity remain `unknown`.
- Confirmed Slack rejection remains `failed/provider_rejected`.

## Testing Strategy

E2E-first acceptance is represented at the explicit provider boundary because the test
suite uses deterministic Slack HTTP fixtures:

1. Toolkit test: `channel_action.files` forwards canonical authority and documents the
   two accepted source forms.
2. File-transfer tests: Runtime and Exchange preflight share count/per-file/aggregate
   limits; exchange authorization denial, unsupported schemes, and byte mismatch fail
   closed.
3. Delivery tests: post-commit Exchange re-resolution streams the authorized body;
   missing authority or changed source prevents provider publication.
4. Slack adapter test: capture the actual completion request and assert its form content
   type and serialized fields, including multi-file order.
5. Focused backend tests run the affected modules; Python format, lint, type checking,
   and the full required suite run before PR creation.

## Rollout and Rollback

The change requires no schema migration or database upgrade. It is backward compatible
for existing Runtime manifests. Rollback removes Exchange selection and restores the
previous code path; no file bytes or new durable resource need cleanup.

## Feasibility

| Requirement | Status | Evidence |
| --- | --- | --- |
| `REQ-1` | Feasible | Existing Tool validation and outbound preflight centrally classify paths. |
| `REQ-2` | Feasible | `TurnContext` carries `SessionResourceAuthority`; Exchange service already enforces it. |
| `REQ-3` | Feasible | Existing system settings and bounded manifest/streaming checks are reusable. |
| `REQ-4` | Feasible | Slack adapter owns the request helper and has MockTransport request-body tests. |

## Non-blocking Risks

Exchange storage resolution is whole-file rather than streaming. The configured outbound
limits bound this behavior and a streaming storage API is outside this focused change.
