---
title: "External Channel File Transfer"
created: 2026-07-23
tags: [slack, external-channel, files, delivery, architecture]
document_role: primary
document_type: adr
snapshot_id: files-260723
---

# External Channel File Transfer

- Snapshot: `files-260723`
- Requirements: [`files-260723/REQ`](../requirements/files-260723-external-channel-transfer.md)

## Context

The current Slack admission projection retains bounded message and Block Kit fields
but omits Slack `files[]`. Canonical External Channel message revisions store
provider-neutral text and JSON metadata without downloading provider files, and
promoted external input intentionally contains no Exchange attachments or ModelFiles.

The existing `channel_action` contract commits canonical work state and durable provider
delivery intents before one-attempt Slack mutations. It currently supports text replies
and progress/control message operations, but not runtime-file staging or Slack's
multi-step external upload flow. Runtime file reads and writes operate through the
Runtime Runner and currently transfer complete byte payloads.

Slack file access requires additional `files:read` and `files:write` bot scopes that are
not part of the current required connection capability. The System Settings framework
supports typed, versioned instance-level configuration sections, but no External Channel
file-transfer section exists.

The confirmed Requirements fix the following boundaries and they are not ADR decision
points:

- inbound content is downloaded only after an explicit Agent request using an opaque key
  and runtime destination;
- inbound transfer handles one file per request and does not automatically create
  Exchange or ModelFile resources;
- outbound files extend the existing explicit Channel publication action and may contain
  multiple runtime files;
- Slack directly uploaded files are the only supported first-release inbound mode;
- attachment access is scoped to the active linked Channel conversation and current
  provider authorization; and
- per-file limits default to 25 MiB with configurable per-file and aggregate limits.

## Decision Backlog

| Order | Decision point | Dependency | Status |
| --- | --- | --- | --- |
| DP1 | Slack file-scope rollout and capability policy | None | Accepted as ADR-D1 |
| DP2 | Canonical inbound attachment identity and lifecycle | DP1 | Accepted as ADR-D2 |
| DP3 | Outbound runtime-file stabilization boundary | None | Accepted as ADR-D3 |
| DP4 | Text and multi-file delivery atomicity and partial-failure contract | DP3 | Accepted as ADR-D4 |
| DP5 | System-setting scope and provider override policy | None | Accepted as ADR-D5 |

This backlog contains only hard-to-reverse architecture or product-contract choices
requiring requester judgment. Reversible implementation details remain Design-owned. If
the backlog changes, the complete revised list must be briefed before the next decision
is discussed.

## Decisions

### files-260723/ADR-D1. Represent Slack file read and write as independent optional capabilities

**Affects:** `files-260723/REQ-2`, `files-260723/REQ-4`,
`files-260723/REQ-6`, `files-260723/REQ-7`

Keep the existing Slack messaging capabilities active when file scopes are absent.
Represent inbound download and outbound upload as independent provider-neutral
connection capabilities. Slack grants `download_files` from `files:read` and
`upload_files` from `files:write`.

Connection validation derives the granted scopes from Slack's authenticated Web API
response metadata. Missing or unparseable scope evidence never grants a file capability.
The actual file operation remains an authoritative fail-closed check and may report that
the required capability is unavailable if Slack rejects the token. New generated Slack
App configuration requests both file scopes, while an existing installation can add
either scope without losing unrelated text conversation behavior.

**Rejected:** Making both file scopes mandatory for the entire Slack connection would
interrupt existing text-only conversations until every App is reinstalled. Treating both
directions as one optional capability would unnecessarily disable a granted read or write
direction when only the other scope is absent.

### files-260723/ADR-D2. Use a plain self-contained file locator and delegate file authorization to the provider

**Affects:** `files-260723/REQ-1`, `files-260723/REQ-2`,
`files-260723/REQ-3`, `files-260723/REQ-7`

Represent each observed attachment with bounded metadata and one versioned
provider-neutral key. The key may directly encode the provider, active binding or
connection identity, and provider file identity. It requires neither encryption nor a
cryptographic integrity signature, and no dedicated attachment entity or key lookup is
created.

At download time, Azents verifies only that the current Agent and Session own the
referenced active binding and connection and that the connection has the required file
capability. It then asks the provider for current file metadata and content using that
connection's credential. The provider response is authoritative for whether the file is
visible and downloadable.

Azents does not compare the decoded provider file identity with immutable attachment
membership in the originating message revision. Modifying the file identity in a key may
therefore select another file that the same connected Slack App is permitted to access;
Slack rejection remains the access-denial boundary.

**Rejected:** A dedicated attachment entity, encrypted locator, HMAC signature, or
revision-membership proof would introduce an additional Azents authorization or
integrity boundary that the requester did not require.

### files-260723/ADR-D3. Stream outbound Runtime files directly to the provider without durable staging

**Affects:** `files-260723/REQ-5`, `files-260723/REQ-6`

Keep the Runtime path as the outbound file source for the immediate one-attempt Channel
delivery. Before committing the action, stat every selected path and validate its
per-file and aggregate declared size. After the durable delivery intent commits, read
each file from the Runtime in fixed-size chunks and stream those chunks directly to the
provider upload URL. Upload multiple files sequentially so memory use remains bounded by
one transfer chunk rather than aggregate attachment size.

Do not create an Exchange file, Artifact, or private durable staging object for Channel
delivery. The first release does not provide a stable open-file snapshot while streaming
and does not resume an interrupted upload from its last chunk. Runtime mutation,
disappearance, cancellation, or an ambiguous transport outcome after commit is classified
through the existing one-attempt delivery result rather than recovered from staged bytes.

**Rejected:** Reading complete files into application memory scales memory with file and
aggregate limits. Durable Exchange or private staging adds persistence and cleanup
lifecycle that the requester did not require. Resumable multipart delivery is not part of
Slack's documented upload flow and would exceed the first-release contract.

### files-260723/ADR-D4. Publish text and all files as one provider-visible reply with one outcome

**Affects:** `files-260723/REQ-5`, `files-260723/REQ-6`

Treat the text and every selected file in one Channel publication action as one logical
provider reply and one durable delivery outcome. Acquire and stream each provider upload
sequentially, but do not publish the reply until every file upload has succeeded. Complete
all uploaded files together with the conversational text in the bound Slack root thread.

If any pre-completion upload fails, do not complete or publish the reply and terminalize
the complete delivery as failed or unknown according to the provider result. A confirmed
completion marks the complete reply delivered. An ambiguous completion marks the complete
reply unknown. Do not automatically replay any upload or completion step.

Text-only Channel replies continue to use the existing provider message path. A
file-bearing reply may use the provider's file-publication path internally, but it remains
the same model-visible `channel_action` publication and produces one combined outcome.

**Rejected:** Separate text and file attempts permit partial visibility and can create
multiple Slack messages for one Agent reply. Completing each file independently conflicts
with the requirement to attach multiple runtime files to one publication action.

### files-260723/ADR-D5. Apply one provider-neutral External Channel file-limit policy

**Affects:** `files-260723/REQ-5`, `files-260723/REQ-7`

Add one typed instance-level External Channel file-transfer System Settings section. It
defines the inbound per-file limit, outbound per-file limit, and outbound aggregate limit
for one Channel publication action. The per-file defaults are 25 MiB. The configured
policy applies uniformly to every External Channel provider.

Provider adapters may enforce stricter provider or workspace limits, but they do not
expose provider-specific overrides in the first release. The outbound stream chunk size
is an internal implementation constant rather than an administrator setting.

**Rejected:** A Slack-only settings section would make the product policy
provider-specific. Global defaults plus provider overrides add precedence, validation,
and management complexity without a second provider or a confirmed operational need.
