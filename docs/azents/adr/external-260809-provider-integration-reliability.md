---
title: "External Channel Provider Integration Reliability Decisions"
created: 2026-08-09
tags: [architecture, external-channel, slack, discord, sdk, reliability]
document_role: primary
document_type: adr
snapshot_id: external-260809
---

# external-260809/ADR: External Channel Provider Integration Reliability

## Context

The confirmed
[external-260809/REQ](../requirements/external-260809-provider-integration-reliability.md)
requires Slack and Discord provider operations to use the currently adopted SDK public
API whenever that SDK supports the required operation. Direct REST is permitted only
for the exact operation that the adopted SDK does not publicly support while preserving
the current product contract.

The requester fixed the convention and SDK trust boundary:

- SDK supports the operation: use the SDK;
- SDK does not support the operation: use a narrow direct REST call;
- Slack uses the currently adopted `slack-sdk`;
- Discord uses the currently adopted `discord.py`;
- do not add Hikari, another Discord SDK, another language runtime, a sidecar, or an IPC
  boundary to replace provider calls; and
- do not retain an SDK/direct compatibility fallback.

Slack Web API, Slack Socket Mode, and Discord Gateway already use SDK public APIs for
most operations. Hand-written transport remains in Discord application, command,
message, thread, history, and attachment adapters and in Slack private-file and
external-upload byte transfer.

## Decision Backlog

1. **Accepted: the adopted SDK public API owns every operation it supports.**
2. **Accepted: direct REST remains only for exact adopted-SDK capability gaps.**
3. **Accepted: SDK results and exceptions replace raw provider response contracts for SDK-supported operations.**
4. **Accepted: deterministic tests use SDK-facing collaborators and explicit direct-gap fakes without private SDK APIs.**

## Decisions

### external-260809/ADR-D1 — Use only the currently adopted provider SDKs

Slack provider operations use public `slack-sdk` APIs. Discord provider operations use
public high-level `discord.py` APIs. The migration does not add Hikari or another
Discord SDK based only on endpoint coverage, and it does not add Node, discord.js, a
sidecar, a subprocess protocol, or an embedded second-language runtime.

SDK support is evaluated per provider operation. An operation is SDK-supported when the
adopted SDK public API can perform the required provider effect while preserving the
operation's required identity, authority, bounded-data, and provider-effect contract.
When supported, the direct route, raw response decoder, and duplicate fallback are
removed.

This decision applies to `external-260809/REQ-1`, `REQ-2`, `REQ-5`, and `REQ-7`.

Adding Hikari is rejected because it is not an approved trusted SDK for this service.
Adding a cross-language SDK adapter is rejected because the existing provider service
is Python and the requester requires the native adopted SDK or direct REST when that
SDK lacks support.

### external-260809/ADR-D2 — Map Discord operations to `discord.py` before admitting REST gaps

The following Discord operations move to or remain on public `discord.py` APIs:

- client login, current Application metadata, Application Interaction Endpoint edit,
  and current Bot identity;
- command list and individual edit/delete through public application-command objects;
- channel and thread fetch, root-message thread creation, and thread edit;
- exact-message fetch and paginated message history;
- text-only Create Message with the existing operation nonce, which `discord.py`
  lowers with `enforce_nonce=true`;
- message edit and delete; and
- attachment metadata refresh through the SDK-returned Message and Attachment models.

Azents calls the public SDK operation once. SDK-owned rate-limit and transport handling
remains inside that invocation; Azents does not reproduce it, issue a raw fallback, or
replay an ambiguous result after the SDK call finishes. The final public SDK result or
exception is normalized into the existing provider-neutral success, `failed`, or
`unknown` outcome where applicable.

The following are exact `discord.py` capability gaps and may remain direct REST:

1. create one required Guild command without bulk synchronization that could remove
   unrelated customer-owned commands;
2. multipart Create Message from a bounded async Runtime or Exchange byte stream without
   full-file buffering or unrelated temporary storage;
3. attachment CDN `HEAD` and bounded streaming `GET` with redirects rejected before
   following them.

Direct command list, update, and delete are not exceptions because public SDK methods
support them. Direct text-only message create, edit, delete, channel/thread, Application,
identity, and history routes are not exceptions.

This decision applies to `external-260809/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`,
and `REQ-7`.

Using `CommandTree.sync()` for reconciliation is rejected because bulk synchronization
would make the local tree authoritative over unrelated customer commands. Using
`Attachment.read()` or `Attachment.save()` for provider transfer is rejected because
those public helpers buffer the complete body. Using `discord.File` for the existing
bounded async source is rejected when it would require complete buffering or unrelated
temporary storage.

### external-260809/ADR-D3 — Keep Slack control-plane operations SDK-owned and isolate byte-transfer gaps

All Slack Web API operations use public high-level `AsyncWebClient` methods with the
existing non-propagating logger and disabled retry handlers. This includes validation,
identity, conversation and history reads, permalink and file metadata, message/view
mutations, upload-target acquisition, and upload completion. Slack Socket Mode remains
on the public SDK client and request/response types.

Direct Slack HTTP remains only for:

1. authenticated private-file `HEAD` and bounded streaming `GET` after SDK-owned
   `files.info` resolves the current metadata and private URL; and
2. bounded streaming `POST` to the provider-issued external upload URL after
   SDK-owned `files.getUploadURLExternal` and before SDK-owned
   `files.completeUploadExternal`.

These are SDK capability gaps because the public Slack SDK exposes no general private
file streaming operation and its public upload wrapper reads the complete file into
bytes. The direct transports preserve the existing origin allowlist, authorization,
exact content length, chunk and aggregate bounds, one-attempt behavior, authority
revalidation, sanitized errors, and ambiguous-outcome classification.

This decision applies to `external-260809/REQ-1`, `REQ-3`, `REQ-4`, `REQ-5`, and
`REQ-7`.

Calling the Slack SDK private upload helper is rejected. Buffering the complete file to
use `files_upload_v2` is rejected because it does not support the required bounded
streaming operation.

### external-260809/ADR-D4 — Direct transports form a closed allowlist with deterministic SDK-facing tests

Direct provider transport is restricted to the five exact gaps accepted by
`external-260809/ADR-D2` and `external-260809/ADR-D3`:

- Discord individual Guild command creation;
- Discord bounded multipart file-message creation;
- Discord attachment CDN `HEAD`/streaming `GET`;
- Slack authenticated private-file `HEAD`/streaming `GET`; and
- Slack provider-issued external-upload streaming `POST`.

Each exception is operation-specific and owns no general provider client, no
provider-wide route builder, no WebSocket protocol, and no fallback for SDK-supported
operations. Its removal condition is an adopted SDK public API that supports the same
operation and required contract; migration then replaces the exception rather than
retaining both paths.

SDK-supported history uses public SDK objects and preserves deadline, page-count,
scanned-message, retained-message, identity, relationship, and normalized per-message
bounds. The obsolete pre-parse raw-response byte check is removed with the direct
history transport rather than used to justify retaining an SDK-supported route.

Production adapters expose narrow Azents-owned SDK-facing protocols. Deterministic
unit and E2E fixtures inject those protocols or the explicit direct-gap transport
interfaces. Tests do not mutate private SDK route globals, instantiate private SDK HTTP
clients, reconstruct private SDK state, or require live provider credentials.

Static repository checks reject new Slack or Discord route literals, generic provider
HTTP clients, private SDK imports, and direct-call fallbacks outside the exact exception
modules and their deterministic fakes.

This decision applies to `external-260809/REQ-1`, `REQ-5`, `REQ-6`, and `REQ-7`.

## Consequences

- Provider SDK trust remains limited to the already adopted `slack-sdk` and
  `discord.py` dependencies.
- SDK-supported operations lose their direct HTTP clients, route builders, raw response
  parsing, duplicate retry logic, and route-level test fixtures.
- Five exact capability gaps retain narrow direct REST transport until the adopted SDK
  adds suitable public support.
- Discord history normalization begins from public SDK models rather than raw provider
  JSON while retaining product-level bounded context.
- The production image remains Python-only and adds no additional Discord SDK.
- SDK-internal behavior is observed only through public results and exceptions; Azents
  retains canonical state, authority, ordering, and final product classification.

## Risks

- `discord.py` model shapes differ from the current raw JSON dictionaries; normalization
  tests must prove equivalent bounded projections and identity checks.
- SDK internal retry or rate-limit handling may affect operation duration. Existing
  absolute deadlines and post-call classification must not create a second attempt.
- Direct gap modules could expand accidentally unless static checks enforce the exact
  route and operation allowlist.
- Future SDK releases may add public support for a current gap; dependency upgrades must
  re-evaluate and remove obsolete exceptions.
