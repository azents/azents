---
title: "Adopt Agent File Exchange Storage Separate from Sandbox Workspace"
created: 2026-05-05
tags: [architecture, backend, engine, api, infra, frontend, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: file-260505
historical_reconstruction: true
migration_source: "docs/azents/adr/0007-agent-file-exchange-storage.md"
---

# file-260505/ADR: Adopt Agent File Exchange Storage Separate from Sandbox Workspace

## Context

NoIntern's existing file paths mixed File API, EFS, `/data/*`, `shared:///session/*`, and `/home/sandbox`. Web uploads were stored by the backend through the File API under `/data/uploads/{session_id}/...`, and Slack/Discord file bridges read and wrote files through the same File API layer. The LLM-facing file tool also accepted either File API or sandbox daemon injection and handled both through the same `FileStorage` protocol.

However, in the agent-centric raw session and optional dedicated sandbox architecture, files have two different lifecycles.

1. Files uploaded by users or offered to users as downloads need UI/API contracts, TTL, quota, and audit.
2. Files read and written by shell and file tools inside the sandbox need the active filesystem path as the canonical source, and checkpoints should cover `/home/sandbox/**`.

If these two axes are merged into one EFS/File API path, upload handling for sandboxless agents, artifact download, hibernated sandbox restore, and TTL enforcement become hard to define consistently.

## Decision

Adopt the following principles:

1. Remove the File API and EFS-backed `/data/*` file layer.
2. Exchange Storage is the canonical storage for user uploads and artifact downloads.
3. Exchange Storage URIs use stable logical URIs:
   - `exchange://uploads/{file_id}`
   - `exchange://artifacts/{file_id}`
4. Events and messages store stable exchange URIs and display metadata, not presigned URLs.
5. Phase 1 of Web upload ingest starts with a backend multipart proxy. Presigned PUT/finalize is only a future optimization. Slack/Discord inbound attachment ingest is handled by a separate design.
6. The canonical path for sandbox filesystem state is `/home/sandbox/**`. `/tmp/**` is transient and is not checkpointed.
7. Files are not imported into the sandbox automatically. The model must explicitly call `import_file(exchange_uri, target_path?)`. The default import location is `/tmp/agent/uploads/{filename}`.
8. `present_file(path)` exports a `/home/sandbox` file as an Exchange artifact and shows the user a stable artifact URI.
9. Sandboxless agents can receive image uploads as LLM image input. Non-image uploads are passed to the LLM as metadata only; reading or manipulating their contents requires sandbox configuration.
10. Sending files back as Slack/Discord attachments is out of scope. This design only implements Web download links.
11. Exchange object storage and sandbox checkpoints may reuse the same S3-family infrastructure, but their prefixes and lifecycle policies are separate. Sandbox checkpoint identity is based on AgentRuntime, not AgentSession.

## Consequences

### Positive

- Removes File API/EFS/`/data` dependencies and simplifies the file path model.
- Sandboxless agents can still handle upload metadata and image input.
- Sandbox workspace checkpointing is narrowed to `/home/sandbox/**`.
- User download/export URLs are resolved to presigned URLs at request time, letting the backend consistently enforce expiration and permission checks.
- Artifact export separates event metadata from storage lifecycle, so old events can still show which files existed even when storage lifecycle changes.

### Negative

- Existing APIs, tests, and UI built on `/sessions/{id}/session-data`, `/shared-data/{scope}`, and `/data/uploads/*` must be rewritten.
- Code that used `FileStorage` as a shared abstraction for File API and sandbox daemon must be split.
- New DB model, repository, service, and S3 lifecycle configuration are needed for Exchange metadata.
- Slack/Discord file attachment delivery is reduced until a separate design is introduced.
- Memory, generated images, and tool output overflow previously tied to `/data/agent` need replacement storage paths before Exchange Storage implementation.

## Alternatives

### Make sandbox filesystem canonical for all files

Rejected. Sandboxless agents would be unable to handle uploads, and user uploads would wake the sandbox. Upload/download TTL, quota, and permission audit would also become tied to the active filesystem and conflict with hibernation.

### Make object storage canonical for all files

Rejected. Shell and file tools operate against a POSIX filesystem. If object-per-file sync is the canonical active-state model, editing, grep, glob, generated artifact discovery, and checkpoint consistency become complicated.

### Keep File API and `/data/*`, replacing only the backing store with S3

Rejected. The path contracts themselves—`/data/agent`, `/data/user`, `/platform`, `/data/uploads`—do not fit the agent-centric sandbox model. Without a clean removal, old path compatibility would remain in runtime prompts and tool descriptions.

### Use presigned browser direct upload in Phase 1

Rejected. Browser direct upload is useful for large files, but adds CORS, finalize idempotency, orphan cleanup, and content-type validation. First fix the storage model and runtime semantics with a backend multipart proxy, then optimize.

## Status

Accepted. The detailed design follows `docs/nointern/design/file-260505-file-exchange.md`.

## Migration provenance

- Historical source filename: `0007-agent-file-exchange-storage.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
