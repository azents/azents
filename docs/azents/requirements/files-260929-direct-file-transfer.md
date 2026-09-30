---
title: "Direct File Transfer and Consistent File Limits Requirements"
created: 2026-09-29
updated: 2026-09-29
implemented: 2026-09-30
tags: [files, runtime, chat, external-channel, transfer]
document_role: primary
document_type: requirements
snapshot_id: files-260929
---

# Direct File Transfer and Consistent File Limits Requirements

- Snapshot: `files-260929`
- Document reference: `files-260929/REQ`

## Problem

The same file can be accepted by one Azents file surface and rejected by another because independent file-transfer paths enforce 8, 20, 64, 128, or 500 MiB limits. Some paths also relay complete-file bytes through application services even when S3-compatible storage is the source or destination. Users cannot reliably move a supported file between Chat, Agent Workspace, Agent tools, and downloads.

## Primary Actor

A person exchanging a file with an Agent in Chat and using its Agent Workspace.

## Primary Scenario

The person attaches a file within the common size limit, the Agent brings it into the Runtime to work on it, and the Agent makes a resulting file available for the person to download. Each eligible general-purpose file transfer succeeds without an unrelated, lower intermediate-hop limit or a complete-file application relay.

## Supporting Scenarios or Effects

- An Agent stores the output parts of another Tool in the Runtime, including parts already held in S3 and parts supplied by the Tool as bytes.
- An Agent receives an external-channel file or sends a Runtime file to an external service.
- An Agent reads a Runtime image as model input, subject to a distinct image-input policy.
- A person uploads a file to or downloads a file from Agent Workspace, or downloads an Exchange attachment.
- An operator diagnoses cancellation, integrity failure, expired file authority, or a file that exceeds an applicable limit.

## Goals

- Use one 128 MiB per-file limit for eligible general-purpose direct S3-compatible file transfers, with no lower hidden transfer-hop limit.
- Move eligible complete-file bytes directly between their endpoint and S3-compatible storage without routing the bytes through the public API or Runtime Control application processes.
- Preserve the existing file identities, access checks, integrity guarantees, and safe failure behavior.
- Keep independently meaningful image-input and external-service delivery policies separate from the general-purpose file-transfer limit.

## Non-Goals

- Increasing the common 128 MiB number in this snapshot; its value may be reconsidered in later work.
- Making external services accept files beyond their own effective outbound limits or bypassing existing external-channel outbound administrator policy.
- Increasing the image-input size limit or requiring a model to ingest the complete contents of every accepted attachment.
- Giving the Runtime or browser persistent S3 credentials, bucket-wide access, or authority to choose arbitrary storage keys.
- Changing unrelated bounded text, process output, filesystem inspection, or provider-model limits solely because they also have byte counts.

## Requirements

### REQ-1. Consistent general-purpose file size eligibility

Every in-scope general-purpose direct file transfer must allow one file through 128 MiB inclusive and reject a larger file with an attributable size-limit result, rather than accept it at one surface and reject it at a smaller internal transfer hop.

**Acceptance criteria**

- A file exactly 134,217,728 bytes is eligible at each in-scope general-purpose transfer boundary, subject to authorization, destination capacity, and other independent product policies.
- A file one byte larger is rejected at the applicable 128 MiB boundary before destination publication.
- The 8 MiB Worker transfer bound, 20 MiB Chat upload bound, and 64 MiB Workspace download bound no longer prevent otherwise eligible general-purpose transfers.
- An external-channel inbound file above 128 MiB is no longer eligible for Runtime materialization; the former 500 MiB inbound eligibility does not override this common bound.
- The common number is represented as one coherent policy across in-scope surfaces, without unintentionally changing unrelated policy limits.

### REQ-2. Direct storage data path with bounded authority

After a file is present in trusted S3-compatible storage, its complete bytes must reach the Runtime without an intermediate application byte relay; files produced by the Runtime must reach storage without a Runtime Control byte relay. Browser upload and download must likewise use storage as their byte data path. Provider ingestion and Tool-owned output production remain separately authorized source boundaries.

**Acceptance criteria**

- Eligible inbound files reach the Runtime from storage without a complete-file Runtime Control byte stream, including Exchange/Artifact/managed imports, all saved Tool output parts after any required source staging, and externally sourced files after provider ingestion.
- Eligible files sent from the Runtime to storage do not send their complete bytes through Runtime Control, including user-facing file presentation, external-channel Runtime file delivery, model-input image source transfer, and Workspace downloads.
- Chat upload bytes do not traverse the public API; a successfully authorized user upload still becomes an Exchange attachment.
- Browser downloads of Workspace files and Exchange attachments do not relay their complete bodies through the public API.
- Metadata, authorization, transfer coordination, and publication remain under trusted server authority; neither a storage object nor a transient read/write capability by itself authorizes a product action.

### REQ-3. Preserve Agent file-tool behavior

The Agent must retain the existing observable identity, destination, result, and recovery semantics of file tools while the complete-file transport changes.

**Acceptance criteria**

- `import_file` retains supported source kinds, authorization checks, destination behavior, and the temporary-versus-durable path distinction.
- `run_tool_to_file` stores every eligible output-part kind with per-part success/failure accounting and its manifest, without re-executing the target Tool after a storage failure; each part may be up to the common limit subject to its producing Tool's own policy.
- `present_file` still publishes only authorized Agent Workspace files as Exchange attachments after verified bytes and metadata are available.
- `channel_action` can use a Runtime file as an outbound source after verified storage transfer without creating an Exchange attachment merely to send it.
- `read_image` can transfer a supported image without the unrelated 8 MiB hop limit, while its 20 MiB image-input limit and model-image normalization remain authoritative.

### REQ-4. Preserve external-channel policy boundaries

External provider ingress and egress must keep their separate authentication, provider, and outbound-policy boundaries while their in-scope storage-to-Runtime or Runtime-to-storage hop changes.

**Acceptance criteria**

- `download_external_file` accepts an authorized provider file only up to 128 MiB into the Runtime; provider-origin verification and exact-byte checks remain in force.
- For outbound `channel_action` files, effective provider and administrator limits remain authoritative even when the internal Runtime-to-storage hop can handle 128 MiB.
- A lower provider or administrator outbound limit is reported as that policy boundary, not misrepresented as an internal Runtime transfer failure.

### REQ-5. Preserve secure publication and failure handling

Transient storage access must be limited to the exact authorized operation, and incomplete, changed, oversized, cancelled, or unverified content must never become a committed Runtime destination, Exchange attachment, or successful provider publication.

**Acceptance criteria**

- Expired or revoked Session, Agent, Workspace, Exchange, external-channel, Runtime-generation, and requester authority is rechecked at the applicable decision boundaries.
- The exact file size and content integrity are verified against trusted evidence before publication; a failed check leaves no committed new destination.
- Transient storage access and temporary objects have bounded lifetimes and cleanup ownership; capabilities are not exposed to the model, stored in ordinary message history, or logged as credentials.
- A browser download authorized by a short-lived capability may outlive the issuing request; its expiry and temporary-object cleanup are bounded, without claiming that the application observes the browser's actual download completion.

### REQ-6. Retain attachment and model-input distinctions

A large user attachment must remain available for its authorized file workflows without assuming the model can consume the original entire body as inline input.

**Acceptance criteria**

- A successfully uploaded Chat file within 128 MiB remains a user-facing Exchange attachment available to authorized download and Runtime import.
- The distinct model-input materialization policy still limits model-facing bodies; it cannot cause an otherwise valid attachment to be rejected solely because the model cannot ingest it.
- Preparing an accepted large attachment for a message does not require an unbounded complete-file read into an application process solely to determine that it is ineligible for model input.

## Fixed Constraints

- S3-compatible object storage remains private; browsers and Runners receive no long-lived object-storage credentials or bucket-wide authority.
- The general-purpose per-file limit for this snapshot is 128 MiB = 134,217,728 bytes. The requester deferred changing that number to later work.
- The explicit `read_image` source-image limit remains 20 MiB, independently of the storage-transfer bound.
- External-service and existing external-channel administrator outbound file/action limits remain authoritative; this snapshot does not raise them.
- The earlier implemented Requirements and ADRs remain immutable; this snapshot supersedes only the current behavior expressly changed here.

## Open Assumptions

- A supported deployment can provide a reachable S3-compatible endpoint for each direct browser and Runtime transfer direction while preserving existing network-policy authority.
- Existing Exchange objects over 128 MiB, if any, would become ineligible under the requested direct-download limit; their presence and rollout impact should be measured before implementation.

## Confirmation

Confirmed by the requester on 2026-09-29 before the associated ADR and Design were created. The requester confirmed the consolidated scope after reviewing the tool paths one by one, including the reduction of external-channel inbound eligibility from 500 MiB to 128 MiB.
