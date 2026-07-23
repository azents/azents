---
title: "External Channel File Transfer Requirements"
created: 2026-07-23
updated: 2026-07-23
tags: [slack, external-channel, files, agent]
document_role: primary
document_type: requirements
snapshot_id: files-260723
---

# External Channel File Transfer Requirements

- Snapshot: `files-260723`
- Document reference: `files-260723/REQ`

## Problem

External Channel conversations can carry text between Slack participants and an Agent,
but the Agent cannot selectively obtain files attached to an inbound Slack request or
return generated files with its reply. Automatically copying every attached file into
Azents or model context would expose content that the Agent may not need and would make
provider-specific file access part of the conversation contract.

## Primary Actor

An approved Slack channel participant collaborating with a connected Agent on a request
that includes input files or requires file-based results.

## Primary Scenario

A Slack participant attaches one or more files to a message that invokes the Agent. The
Agent sees bounded metadata and an opaque reference for each supported attachment,
explicitly obtains only the selected file into its runtime, processes it, and explicitly
sends an explanation together with one or more generated runtime files to the same Slack
thread.

## Supporting Scenarios

- A message contains several attachments, and the Agent obtains only the attachments
  needed for the request, one at a time.
- The Agent obtains the same attachment again during a later turn while the linked
  Channel conversation remains active.
- An attachment becomes unavailable because the connection was disconnected, access was
  revoked, or the Slack file was deleted, and the Agent receives a clear failure instead
  of stale content.
- An Agent sends several runtime files with one explicit Channel reply.
- An unsupported or oversized file remains identifiable by metadata but is rejected when
  transfer is requested.

## Goals

- Let Agents selectively process files shared with authorized External Channel requests.
- Keep inbound file bytes out of model context and Azents file storage unless the Agent
  explicitly requests the content.
- Let an explicit External Channel reply include generated files without introducing a
  separate upload-only Agent action.
- Preserve provider-neutral Agent behavior while delivering the first implementation for
  Slack.
- Bound transfer size and make unsupported, unavailable, and policy-rejected transfers
  clear to the Agent.

## Non-Goals

- Automatically copying inbound Slack files into Exchange, ModelFile, or model context.
- Supporting Slack external or remote files, Slack Connect files, or sparse file records
  that require separate access resolution in the first release.
- Supporting External Channel providers other than Slack in the first release.
- Obtaining multiple inbound files in one Agent transfer request.
- Adding a separate Agent action whose sole purpose is uploading a file to an External
  Channel.

## Requirements

### REQ-1. Discoverable inbound attachments

Every supported file attached to an invocation-eligible Slack message must be represented
to the Agent without exposing the file content or a provider download URL.

**Acceptance criteria**

- A message with multiple attached files exposes each attachment separately.
- Each attachment includes bounded decision-useful metadata, including its filename or
  title, media type when available, and declared size.
- Each attachment includes an opaque unique key that the Agent can use to request that
  file.
- Private download URLs, credentials, and file bytes are not exposed in Agent-visible
  message content.
- Provider file identifiers may be encoded in the opaque key; the Agent is not required
  to parse or supply them separately.
- Receiving or promoting the message does not automatically create an Exchange file,
  ModelFile, runtime file, or direct model file input.

### REQ-2. Explicit single-file materialization

The Agent must be able to explicitly obtain one selected inbound attachment at a requested
runtime destination.

**Acceptance criteria**

- One transfer request accepts one attachment key and one runtime destination path.
- A successful request writes the selected file to the permitted runtime destination.
- Files not selected by the Agent are not downloaded or materialized.
- Repeating the request for the same key is allowed while that key remains valid.
- An invalid destination or failed transfer returns a clear error without presenting the
  file as successfully materialized.

### REQ-3. Binding-scoped attachment access

An inbound attachment key must remain usable only while its linked External Channel
binding and provider access remain active.

**Acceptance criteria**

- The key can be reused across Agent turns while the linked Channel binding is active and
  the Slack file remains accessible.
- A key cannot be used through an unrelated Agent, Session, connection, or Channel
  binding.
- Transfer is rejected after the binding or connection is disconnected.
- Transfer is rejected after provider authorization is revoked or the Slack file is
  deleted or no longer accessible.
- Current provider access is checked when the Agent requests the file rather than relying
  on a previously exposed provider URL.
- The active provider connection is authoritative for whether the requested provider file
  may be accessed.
- Azents does not require the file identity carried by a key to remain immutably bound to
  the message revision where that key was first presented.

### REQ-4. Fail-closed Slack file scope

The first Slack release must transfer only files uploaded directly to Slack that are
available to the connected App in a supported, fully described form.

**Acceptance criteria**

- A directly uploaded, accessible Slack file can be selected for transfer.
- A Slack external or remote file is rejected.
- A Slack Connect file is rejected.
- A sparse file record requiring separate access checking, including
  `file_access=check_file_info`, is rejected.
- Unsupported file modes fail clearly and do not fall back to an external URL or partial
  metadata as file content.

### REQ-5. Configurable transfer limits

Inbound and outbound transfers must be bounded by administrator-configurable limits.

**Acceptance criteria**

- The default maximum size for one downloaded file is 25 MiB.
- The default maximum size for one uploaded file is 25 MiB.
- Administrators can configure the per-file limits.
- Administrators can configure an aggregate size limit for one Agent transfer or message
  publication action.
- A file or combined action that exceeds an applicable limit is rejected before it is
  reported as successfully transferred.
- Provider metadata cannot allow actual transferred content to bypass the configured
  limit.

### REQ-6. File attachments in explicit Channel replies

The existing explicit External Channel message publication action must be able to attach
runtime files to the same conversational reply.

**Acceptance criteria**

- The Agent can publish a Channel reply containing explanatory text and one or more
  runtime files.
- The Agent can attach multiple runtime files in one publication action, subject to the
  configured per-file and aggregate limits.
- The files and conversational reply target the same linked Slack thread as the Channel
  action.
- A missing, unreadable, unsupported, or oversized runtime file produces a clear failure
  rather than a false successful attachment result.
- Ordinary Agent output and Azents Web conversation are not automatically published or
  uploaded to Slack.
- No separate upload-only Agent action is introduced.

### REQ-7. Provider-neutral Agent contract

The Agent-facing file transfer behavior must not require the Agent to understand or
separately supply provider-specific identity, authentication, or transfer procedures.

**Acceptance criteria**

- Inbound selection uses one Azents-defined opaque attachment key. Provider identifiers
  may be encoded in that key and are not separate Agent parameters.
- Outbound selection uses Agent runtime files as part of the existing Channel publication
  behavior.
- Provider-specific authentication and transfer steps remain outside Agent-visible input
  and action parameters.
- Adding a future External Channel provider does not require changing the Agent-visible
  inbound selection or outbound attachment concepts.

## Fixed Constraints

- Slack is the only provider implemented in this snapshot, but the Agent-facing behavior
  remains provider-neutral.
- Inbound file content is materialized only after an explicit Agent request.
- One inbound transfer request handles exactly one file.
- One outbound Channel publication may include multiple runtime files.
- Outbound attachments extend the existing explicit Channel message publication action;
  they are not a separate upload action.
- Attachment keys are opaque and are valid only within the active linked Channel
  conversation and its authorized provider access.
- Provider authorization is authoritative for file visibility; Azents does not add a
  separate message-local file authorization boundary.
- No Slack private URL, credential, or file body is inserted into Agent-visible message
  context.
- Per-file transfer limits default to 25 MiB in both directions, with configurable
  per-file and aggregate limits.
- Unsupported Slack file modes, Slack Connect files, revoked access, and unavailable
  files fail closed.

## Open Assumptions

- The connected Slack App has the provider permissions and channel membership required to
  read a supported inbound file and publish an outbound file.
- Runtime destination and source paths remain subject to the Agent runtime's existing
  filesystem authorization and overwrite policies.
- Slack workspace policies may reject an otherwise valid outbound file independently of
  Azents limits.

## Confirmation

Confirmed by the requester on 2026-07-23 before ADR and design decisions began.
During ADR discussion, the requester clarified that provider file identifiers do not
need confidentiality and may be encoded in the opaque attachment key.
The requester also clarified that Slack authorization, rather than immutable attachment
membership in the originating message revision, determines whether a requested file may
be downloaded.
