---
title: "File Exchange Storage"
created: 2026-05-10
tags: [backend, engine, frontend]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, conversation, workspace, toolkit]
code_paths:
  - python/apps/azents/db-schemas/rdb/migrations/versions/b6088a911203_add_provider_output_provenance.py
  - python/apps/azents/src/azents/core/vfs.py
  - python/apps/azents/src/azents/core/config.py
  - python/apps/azents/src/azents/core/s3/deps.py
  - python/apps/azents/src/azents/runtime/transfer/**
  - python/apps/azents/src/azents/services/external_channel/channel_action.py
  - python/apps/azents/src/azents/services/exchange_file/**
  - python/apps/azents/src/azents/services/external_channel/file_transfer.py
  - python/apps/azents/src/azents/services/file_storage.py
  - python/apps/azents/src/azents/services/artifact.py
  - python/apps/azents/src/azents/services/model_file.py
  - python/apps/azents/src/azents/services/session_resource_authority.py
  - python/apps/azents/src/azents/services/agent_session_input.py
  - python/apps/azents/src/azents/services/vfs.py
  - python/apps/azents/src/azents/repos/artifact/**
  - python/apps/azents/src/azents/repos/model_file/**
  - python/apps/azents/src/azents/repos/agent_session/**
  - python/apps/azents/src/azents/repos/archived_session_retention/**
  - python/apps/azents/src/azents/rdb/models/artifact.py
  - python/apps/azents/src/azents/rdb/models/model_file.py
  - python/apps/azents/src/azents/rdb/models/exchange_file.py
  - python/apps/azents/src/azents/services/session_storage.py
  - python/apps/azents/src/azents/services/archived_session_purge.py
  - python/apps/azents/src/azents/services/uploads/**
  - python/apps/azents/src/azents/services/chat/workspace.py
  - python/apps/azents/src/azents/engine/events/file_parts.py
  - python/apps/azents/src/azents/engine/events/fork_context.py
  - python/apps/azents/src/azents/engine/events/model_file_parts.py
  - python/apps/azents/src/azents/engine/events/model_file_materializer.py
  - python/apps/azents/src/azents/engine/events/provider_output.py
  - python/apps/azents/src/azents/engine/events/generated_files.py
  - python/apps/azents/src/azents/engine/tools/xai_image_generation.py
  - python/apps/azents/src/azents/api/public/chat/v1/**
  - python/apps/azents/src/azents/engine/tools/import_file.py
  - python/apps/azents/src/azents/engine/tools/import_resolver.py
  - python/apps/azents/src/azents/engine/tools/present_file.py
  - python/apps/azents/src/azents/engine/tools/read_image.py
  - typescript/apps/azents-web/src/shared/file-upload/useFileUpload.ts
  - typescript/apps/azents-web/src/features/chat/containers/AttachmentPreviewBarContainer.tsx
  - typescript/apps/azents-web/src/features/chat/components/AttachmentPreviewBar.tsx
  - typescript/apps/azents-web/src/features/chat/components/FileAttachmentList.tsx
  - typescript/apps/azents-web/src/features/chat/components/AttachmentMarkdownPreview.tsx
  - typescript/apps/azents-web/src/features/chat/components/AttachmentPreviewViewer.tsx
  - typescript/apps/azents-web/src/features/chat/components/ChatView.tsx
  - typescript/apps/azents-web/src/features/chat/components/ProviderToolCallCard.tsx
  - typescript/apps/azents-web/src/features/chat/components/ToolActivityGroup.tsx
  - typescript/apps/azents-web/src/features/chat/components/ToolCallCard.tsx
  - typescript/apps/azents-web/src/features/chat/toolActivityPresentation.ts
last_verified_at: 2026-09-05
spec_version: 46
---

# File Exchange Storage

## Overview

File Exchange Storage is the flow that separately stores and retrieves user-facing attachments exchanged between user and Agent, internal Artifacts for agent/tool, managed VFS files, and ModelFiles for LLM rich input. User uploads files from chat input, and Agent imports an external attachment, internal artifact, or current-run managed resource into sandbox with `import_file`, or exposes sandbox file to user with `present_file`. Generated provider image/file output is preserved as canonical file and attachment output parts on one provider tool call instead of storing raw Base64 directly in an event.

External Channel file transfer is a separate explicit Runtime/provider path. It does not
create ExchangeFile, Artifact, ModelFile, FilePart, or another durable file-body object.

ExchangeFile, Artifact, ModelFile, FilePart, preview, download, retention, and model-input
materialization are product storage capabilities and do not require a managed Runtime. Permanent
Runtime removal retains those resources. Only copying bytes into or out of a Runtime Workspace,
reading Runtime paths, and provider delivery from Runtime paths require managed Runtime capability.

### Team Session resource authority and provenance

Public upload, download, and delete operations authenticate and authorize the current requester
before they disclose or mutate a resource. Internal promotion, materialization, import,
presentation, provider output, and Artifact operations instead require a validated
`SessionResourceAuthority` containing canonical Workspace, Agent, exact Session/root Session, Run,
run index, and owner generation. Internal operations never call a public method with a borrowed,
synthetic, nullable, or inferred User.

ExchangeFile ownership is Workspace/Agent scope plus root-session retention binding; provenance is
typed and separate. `source_user_id` records only a Human uploader. Agent, Tool, provider, system,
derived-preview, and historical migration sources use their own typed fields. Source provenance does
not grant execution, retention, or public access. `created_by_user_id` is not an ownership
requirement.

New ModelFiles require exact `created_run_id` together with their Session/run-index lineage. Historical
rows resolve a Run only from the exact `(session_id, created_run_index)` match; unresolved historical
lineage remains null rather than being inferred from a User, owner, uploader, or adjacent resource.
Public ExchangeFile reads remain requester-authorized independently of any stored source, sender,
creator, or Run. ModelFile and Artifact have no public read routes; their internal resolution uses
Session/Run authority.

## Flows

### User upload to chat

1. azents-web `useFileUpload` sends multipart upload to chat API.
2. API verifies workspace/session access, file size, and media type. One upload is
   limited to 20 MiB; the API returns `413` above that boundary, and Main Web
   applies the same byte limit before upload while presenting it as a 20 MB limit.
3. Successful upload creates only the user-facing Exchange attachment. The upload response does not expose a client-owned FilePart.
4. Input acceptance stores and claims the attachment URI. Before the FIFO input is promoted, the worker resolves the claimed attachment outside the database lock, creates a ModelFile, and includes its FilePart in the promoted user message. Deferred action inputs skip this preparation, and a stale, failed, or cancelled promotion marks newly created ModelFiles deleted for lifecycle cleanup.
5. Attachment and FilePart snapshots remain independent in the durable user event. The Attachment supports preview, download, and runtime import, while the FilePart supplies rich model input without requiring the Agent to call `import_file`.
6. Exchange attachment has `status`, `expires_at`, and `expired_at` metadata. Scheduler-owned cleanup marks Exchange files past expiration time as `expired` and attempts blob deletion. Resolver, download API, lowerer, and UI treat expired/unavailable as normal history state based on DB availability.

An ExchangeFile created for a concrete session is bound immediately to that session's root
`SessionAgent` retention unit. Files uploaded before a new root exists remain unbound until the first
input is accepted. Input acceptance atomically claims every referenced source and generated preview
row for the resolved root in the same transaction as the InputBuffer write. Claim rejects missing,
expired, unavailable, cross-workspace, cross-Agent, and already-owned-by-another-root files; a failed
claim rolls back the input. Once bound, metadata resolution, download, `import_file`, and model-input
preparation require the requesting session to resolve to the same root retention unit. Descendant
sessions in that root tree may therefore use the file, while another root under the same Agent may
not.

### Agent imports user or internal file

`import_file` tool uses resolver registry by scheme. Supported schemes are `exchange://{object_key}`, `artifact://{storage_key}`, and canonical `azents://` paths present in the current AgentRun projection. URI is storage location, not entity reference. Do not put business logic that extracts entity id from URI string. Default destination is `/tmp/agent/imports/`, and default destination collisions are deduped with numeric suffix. If explicit destination already exists, fail by default and overwrite only when `overwrite=true`.
Sources larger than the configured Runtime transfer limit fail before admission, and
the tool reports the size-limit rejection without presenting it as a destination-path
failure.
Temporary coordinator admission pressure is retried until capacity becomes available or
the existing transfer deadline expires. Admission timeout, generation fencing, Runner
stream availability, destination write, integrity, cancellation, and unknown transfer
failures retain separate safe tool messages instead of being presented as path
validation failures.
Temporary coordinator connection loss during admission follows the same bounded retry
window and reports a distinct connection timeout when it does not recover. Coordinator
RPC failures that reach the tool retain a structured operation phase, transfer failure
category when available, Session/Run correlation, destination, and exception chain in
operator logs even when the user-facing message withholds internal details.

The tool is projected only when the Agent grants Runtime transfer/filesystem capability. Execution
rechecks the captured capability version before Runtime ensure/start or transfer dispatch, so
Runtime-free, removing, and stale pre-removal calls fail without creating compute or materializing
bytes.

`exchange://{object_key}` materializes a user-visible attachment into a Runtime file.
`artifact://{storage_key}` materializes an agent/tool internal output Artifact into a
Runtime file. Both resolve an authority-checked source manifest and use the common
Server-to-Runtime transfer service; an existing managed S3 object is copied into the
Control-owned immutable transfer object without an application-memory body relay.
Original file bytes are not attached directly to the LLM prompt.

`azents://` materializes one immutable managed file from the current run projection.
The resolver verifies run, Agent, Session, and Workspace ownership, exact projection
membership, Base64 decoding, decoded size, and content hash before incrementally staging
the source into the same Server-to-Runtime transfer service. Ordinary Runtime file
tools do not resolve the URI directly. The source entry remains in the retained AgentRun
projection; only the copied Runtime path follows Runtime persistence rules, and a
default `/tmp/agent/imports/` copy is temporary.

### Agent transfers an External Channel file

`download_external_file` accepts one opaque `external-file:v1` locator and one Runtime
destination from the current active External Channel binding. The service refreshes
provider identity and authorization metadata, then uses only the authenticated final
download URL's HTTP `Content-Length` as the declared transfer size and per-file policy
input (at most 500 MiB). Provider metadata size remains advisory display data and does
not gate download or authority revalidation. The common Server-to-Runtime source
requires the GET response `Content-Length` and incrementally counted body size to match
that declared size, aborting on excess bytes and failing on an early end before any
Runtime destination commit. Runtime admission does not reject an independent valid file
for active-file or aggregate-byte pressure; delivery chunks wait in FIFO-per-file
round-robin order. The Tool result retains only Runtime path, filename, media type, and
verified byte count.

A file-bearing `channel_action` accepts absolute Runtime paths and `exchange://` URIs.
Runtime paths are statted before commit and move through the trusted Runtime
provider-delivery service in one verified upload attempt per source. The
provider receives a bounded native stream from the internally resolved verified object; no
ordinary Runtime range-read relay exposes the complete body to the application. A successful
provider result is followed by authoritative consumer acknowledgement and transfer settlement.
An Exchange URI resolves only under the current canonical `SessionResourceAuthority`, first
at preflight and again immediately before provider upload; both the stored metadata and
returned byte length must match the committed bounded manifest. Relative paths, `artifact://`,
and `azents://` are not outbound source forms. The relay creates no ExchangeFile, Artifact,
ModelFile, FilePart, or other durable product file-body resource. A failed admission,
verification, claim, or stream fails before provider mutation. Once a provider mutation
starts or its outcome is unknown, the transfer is not replayed automatically.

### Agent/tool output artifact

When Agent or MCP-style tool creates internal file artifact, store it as Artifact instead of overloading user-facing attachment. Artifact URI is `artifact://{storage_key}`, and storage key format is `artifacts/{workspace_id}/{session_id}/{created_run_index}/{artifact_id}`. Artifact stores configurable TTL metadata in `expires_at` with default 7 days. Scheduler-owned cleanup marks due Artifacts as `expired` and attempts blob deletion. Resolver rejects access if status is expired regardless of blob existence.

Event transcript keeps only artifact metadata and `artifact://...` URI. Lowerer renders Artifact as bounded metadata text and does not inline raw file body in prompt.

### Explicit FilePart for model rich input

Attachment and Artifact are not generally converted to ModelFile/FilePart. The user-input promotion boundary is the explicit exception for claimed upload attachments: it resolves the Exchange bytes and creates a FilePart before the user event enters model input. Tool implementations that directly have bytes may also create normalized blobs in ModelFileStore and return FilePart. `read_image` first obtains its bytes by claiming a verified Runtime transfer object; Runner Control never carries the image body or Base64 image data. A separate FilePart creation tool exposed to the model is not current contract. FilePart references ModelFile entity by `model_file_id`, not URI. ModelFile itself does not create URI.

ModelFileStore is model input blob store, not original preservation store. Image ModelFile is normalized to JPEG at creation. Non-image ModelFile is not normalized and only size cap applies. ModelFile has current lifecycle status `available` or `deleted`; persistent run-age degradation and `unreachable` stages are not part of the current lifecycle. Scheduler-owned GC deletes unpinned ModelFiles after their single durable FilePart event falls behind the AgentSession model-input head cursor.
If original non-image payload exceeds size cap, ModelFile is not created and is replaced with user-visible size cap message.

Active transcript FilePart referencing deleted or missing ModelFile is rewritten at pre-lower stage into bounded text placeholder in event payload itself. This rewrite applies equally to user messages, assistant messages, client tool results, and provider tool calls, so later compaction, reload, and REST/WebSocket projection do not interpret an unavailable FilePart as rich input again.

When `spawn_agent` forks parent model-visible context into a child session, FileParts are degraded to bounded text placeholders before appending the selected events to the child transcript. Forking does not copy blobs, does not create child ModelFiles, and does not share ModelFile rows through subagent tree context. If the child needs bytes, the parent must hand off a runtime path, exchange/artifact URI workflow, or another explicit transfer outside automatic context fork.

### Generated image materialization

A completed `image_generation` result creates two resources from one transient validated image payload regardless of execution ownership:

1. the original generated bytes become an Exchange file and optional Exchange preview for user preview and download;
2. the shared ModelFile normalization policy creates an independent ModelFile and `FileOutputPart` for later model input.

Provider-hosted execution stores both references in the durable provider call semantic output as `FileOutputPart` and `AttachmentOutputPart`. xAI Imagine execution stores the same output-part kinds on the durable client tool result after its transient generated-file bytes are admitted. Neither event contains Base64, a data URL, raw bytes, provider-native result bytes, or credentials. Exchange and ModelFile media type, size, hash, storage key, authorization, and lifecycle remain independent; neither identity is inferred from the other URI or metadata.

The Engine validates canonical Session/Run resource authority before object upload, closes that
database session, uploads the original, optional preview, and normalized ModelFile object, then
revalidates the same authority while admitting all metadata and the updated tool result in the owning
output transaction. No authenticated actor is required for this internal output path. Partial
materialization is failure. Failed admission compensation deletes only unowned prepared keys.
Deterministic run/call/output identities make retry admission idempotent, reject identity collisions,
and preserve objects already referenced by committed metadata.

Compatible Responses replay of a provider-hosted call resolves the ModelFile and reconstructs provider-native Base64 only inside the outbound request, while a separate bounded item carries canonical Exchange URI context. Cross-adapter provider replay and later-model use of an xAI client result lower the FileOutputPart through normal rich-image input or the explicit unavailable-image placeholder and retain attachment URI metadata. Request-local bytes are never copied back into durable history.

### Archived root purge

Archive does not delete or unbind file resources. Durable purge is an earlier terminal lifecycle
boundary than ordinary file TTL or ModelFile head-cursor GC for every session in the archived root
tree. After purge fencing and run shutdown, the purge workflow:

1. marks subtree ModelFiles deleted, subtree Artifacts expired, and every source/preview ExchangeFile
   bound to the root expired;
2. deletes each external blob and durably records `blob_deleted_at`;
3. verifies that every selected resource reached its terminal metadata and blob state; and
4. deletes file metadata before the root Session cascade.

Any required blob cleanup failure aborts database subtree deletion and leaves ownership, terminal
metadata, durable purge progress, and retry information available for a later pass. Git worktree
state is not a file-storage purge prerequisite: the database-only compatibility participant advances
without Runtime access. Purge never relies on an Exchange URI to infer the owner and never lets a
database cascade erase the last cleanup reference before external deletion succeeds.

### Agent presents sandbox file

`present_file` publishes only files under the current Runner-reported Agent Workspace as a
public Exchange attachment. Files outside the allowed path are rejected. It uses one
Runtime-to-server upload transfer, then publishes the verified immutable transfer
object through a native object-store copy. Product metadata is committed only after
that copy succeeds; a failed, cancelled, changed, oversized, or unverified Runtime
source never becomes an ExchangeFile. The published attachment appears in the chat UI
attachment list and can be retrieved through the download endpoint.

Runtime Transfer state is optional volatile coordination. If its in-memory or Redis
implementation restarts empty, an earlier upload handle cannot be revived from an S3
object, while a new `present_file` operation can start normally. Runtime Control
independently scans its transfer prefix in bounded pages and cleans objects and
incomplete multipart uploads whose storage age is at least the fixed one-hour transfer
lifetime. Object existence alone never creates Exchange publication authority.

Permanent Runtime removal may delete the physical Workspace copy but does not delete an already
published Exchange attachment, retained Artifact, ModelFile, or transcript FilePart. Re-add starts
with a fresh Workspace and never rematerializes retained product files automatically; an authorized
later `import_file` must explicitly copy them into the new Runtime.

## Storage Boundaries

- Event store does not store file body. Event has only attachment/artifact metadata and URI reference, or FilePart `model_file_id`.
- External Channel revisions store bounded provider metadata and opaque locators only.
  A file-bearing `channel_action` keeps its bounded Runtime manifest only for the
  current Tool execution; Session Tool call/result history retains sanitized outcomes
  but no provider URL, transferred bytes, provider payload, or transfer-phase record.
- Durable event, REST/WS projection, and frontend state do not store raw bytes, inline base64, data URL, or provider-specific file payload.
- There is no implicit conversion among Attachment, Artifact, and ModelFile/FilePart. URI is storage location, not entity reference, so do not add logic extracting entity id from URI string. A `model_file_id` is single-event scoped; reusing the same source bytes later requires materializing a new ModelFile/FilePart.
- Attachment ExchangeFile and Artifact have ordinary time-based retention/TTL lifecycle. ModelFile has context-owned lifecycle based on model-input head cursor reachability and active run pins. Archived-root durable purge may terminate any of these resources earlier after purge fencing.
- ExchangeFile archive ownership is explicit `retention_root_session_id` metadata. Source and generated preview rows are claimed together, access is limited to sessions in the same root tree, and ordinary Agent-level namespace membership alone is insufficient.
- User upload, agent-presented file, and internal artifact must pass session/workspace ownership verification.
- ExchangeFile, Artifact, and ModelFile creation preallocates the entity ID and storage key. It
  validates ownership in a short DB session, closes that session before object-storage upload, and
  revalidates ownership while atomically persisting metadata afterward. A failed ordinary upload
  compensation-deletes its preuploaded objects. A verified-object publication with an uncertain
  metadata commit first checks its preallocated publication ID: confirmed absence permits cleanup of
  unowned prepared objects, while a verification query failure or any existing committed identity
  retains the uploaded objects to avoid deleting data that may already be durable. No DB transaction
  spans object-storage I/O.
- Sandbox file query is possible only when active sandbox storage handle exists; inactive/hibernated state follows workspace API action contract.
- General presigned upload such as Agent avatar uses `UploadService` category handler, but it is separate category/publish contract from chat exchange file.
- Trusted object operations use the internal Workspace S3 endpoint. When a separate
  public endpoint is configured, presigned upload and download URLs are generated
  with a dedicated S3 client for that browser-reachable endpoint while retaining the
  same bucket and credentials. Without the optional override, the trusted endpoint
  client also generates presigned URLs.

## UI Contract

- One Composer draft retains at most five selected attachments. Selecting more
  files adds only the remaining available slots. Every selected file is limited
  to 20 MiB before upload, matching the Public API boundary.
- Composer attachments and user-originated sent attachments, including images, render as fixed-width compact tiles in a non-wrapping horizontal strip. Input-buffer projections use the same compact presentation.
- A selected attachment whose upload fails remains removable and expands into a
  bounded error tile with a wrapping filename plus localized failure reason and any
  available detail shown inline. Failure information does not depend on a truncated
  label or hover-only tooltip.
- Attachment strips expose horizontal overflow with a dynamic 40px transparency mask: right edge at the start, both edges in the middle, left edge at the end, and no mask without overflow. Dragging a strip does not activate a tile.
- Agent-originated image-only output renders as an adaptive gallery whenever the original images are available; generated thumbnail metadata is optional. A single image preserves its aspect ratio with a 480px maximum height. Multiple images use square two-column cells, and sets larger than four expose a `+N` count on the fourth visible cell.
- Any client- or provider-tool result with visible Exchange attachments closes the preceding Activity and renders as the ordinary standalone Agent attachment group. Images use the adaptive gallery and non-image files use the compact strip; neither path exposes Base64.
- The attachment-bearing tool call is not duplicated inside Activity. Raw diagnostic cards remain available for non-delivery tool activity, while the standalone attachment group owns preview/download interaction for every visible delivery file.
- Agent-originated non-image files use the compact strip. Mixed Agent output groups the image gallery and compact file strip inside one bordered attachment group.
- Every available sent attachment opens `AttachmentPreviewViewer` from its tile body or gallery cell. The trailing tile download action downloads the original without opening the viewer.
- Exchange-file creation stores a bounded `preview_summary` for safe UTF-8 text. Supported payloads include `text/*`, common textual `application/*` media types, structured media types ending in `+json`, `+xml`, or `+yaml`, `application/octet-stream`, and conservatively recognized text/source/configuration filenames whose declared media type is empty or explicitly generic/unknown. Specific non-text media types are not promoted by filename. Every candidate must decode as UTF-8 without binary control characters. Invalid UTF-8 and binary-control content do not receive a text preview. User uploads and Agent-presented files use this same preview path while retaining the complete original for download.
- `AttachmentPreviewViewer` selects image, Markdown, or plain-text rendering from available preview capability data and shows a download-guidance fallback for other file types. It uses a full-screen mobile overlay and a bounded centered desktop modal with persistent close, metadata, file-position, previous/next, and download controls. Images remain fitted inside the viewer; selecting an image opens the original with inline disposition in the browser's native image viewer. Markdown identified by media type or filename renders GFM without raw HTML, executable custom renderers, or automatic remote-image loading. Other text previews scroll inside a pre-wrapped monospaced surface, and an empty stored preview remains a valid text preview.
- A preview navigates across every available attachment in the rendered attachment group without closing. Users can use the previous/next controls, keyboard arrow keys, a horizontal wheel gesture, or a horizontal touch swipe. Gallery count cells open the first hidden image so every item represented by `+N` remains reachable.
- Opening a preview adds a same-URL browser history entry. Browser Back closes the preview before leaving the conversation, while the close control and Escape consume the same entry.
- Expired or unavailable attachments retain their metadata tile but disable preview and download.
- Closing a preview restores focus to the tile or gallery cell that opened it. Viewer, download, and original-image controls provide localized accessible labels.
- Project management in the concrete Agent session Workspace surface provides existing Agent Workspace folder registration. Project Source upload/delete/load implementation does not currently exist.

## Related Specs

- Conversation event envelope follows [`../domain/conversation.md`](../domain/conversation.md).
- Session Workspace file/project state follows [`../domain/workspace.md`](../domain/workspace.md).
- Tool execution follows [`agent-execution-loop.md`](agent-execution-loop.md).

## Changelog

- **2026-09-04** — v46. Updated the file-upload hook mapping after its
  behavior-preserving move to the shared frontend layer.
- **2026-09-04** — v45. Separated the trusted internal Workspace S3 endpoint from
  the optional browser-reachable endpoint used to generate presigned URLs.
- **2026-09-04** — v44. Mapped the Composer attachment preview container and
  documented data-loss-safe object retention when verified publication commit
  outcome cannot be disproven.
- **2026-09-03** — v43. Kept failed Composer attachments removable while
  presenting their localized reason and available detail inline in a wrapping error
  tile.
- **2026-08-18** — v42. Documented the Main Web five-attachment Composer
  boundary and the shared 20 MiB per-upload client/API limit.

- **2026-08-10** — v41. Separated Runtime-independent product file retention and model input from
  Runtime transfer/materialization authority, added capability/version fencing, and preserved
  Exchange/Artifact/ModelFile resources across permanent Runtime removal and fresh re-add.

- **2026-08-04** — v40. Removed caller-selected and provider-metadata size gating
  from External Channel downloads. The authenticated final URL `Content-Length` is the
  sole declared transfer size, with the streamed body required to match it exactly.
- **2026-08-04** — v39. Removed optional Runtime file-transfer capability gating. Runtime transfer, publication, and provider-delivery services are always bound, while Runtime readiness is resolved only when the corresponding Tool executes.
- **2026-08-03** — v38. Bound `present_file` publication to the current Runner-reported Agent Workspace root instead of Provider metadata or a fixed path.
- **2026-08-02** — v37. Removed the obsolete durable External Channel
  Action/Delivery manifest claim and documented request-local file publication with
  sanitized ordinary Tool results.
- **2026-07-30** — v36. Added bounded verified External Channel ingress up to
  500 MiB; Runtime delivery waits fairly at chunk boundaries rather than rejecting
  independent files for aggregate admission capacity. Caller-selected and metadata
  size gating from this version was removed by v40.
- **2026-07-30** — v34. Reverified the External Channel locator, authority
  revalidation, verified Runtime transfer, provider settlement, and no-durable-body
  boundaries after synchronous ingress contraction; no semantic change.
- **2026-07-30** — v35. Moved Runtime image materialization and Agent Workspace complete downloads onto verified Runtime-to-server transfer objects; bounded text reads use direct strict-decoded Control text rather than Base64 chunks.
- **2026-07-28** — v33. Clarified `present_file` recovery after empty volatile transfer
  state and state-independent one-hour orphan cleanup without reviving S3 objects.
- **2026-07-28** — v32. Promoted the common Runtime File Transfer behavior for
  `import_file`, External Channel ingress, and `present_file`: bounded
  Control-mediated streaming, incremental VFS/provider staging, S3-native
  managed-object copy, verified-object publication, and no application-memory
  complete-file relay.
- **2026-07-26** — v31. Moved Runtime External Channel outbound sources to verified Runtime
  upload and provider-native streaming with post-provider settlement, while preserving the
  no-product-file-side-effect boundary.
- **2026-07-25** — v30. Added authority-resolved Exchange files as an explicit outbound
  External Channel source while retaining Runtime paths and rejecting Artifact, managed
  VFS, and relative sources.
- **2026-07-24** — v29. Separated requester-authorized public file access from
  Session/Run-authorized internal resource operations; added typed Exchange provenance and exact or
  explicitly unresolved ModelFile Run lineage.
- **2026-07-24** — v28. Added formatted safe Markdown attachment preview, empty-text
  preview support, and conservative filename-assisted safe text recognition.
- **2026-07-23** — v27. Distinguished explicit External Channel Runtime/provider transfer
  from Exchange, Artifact, and ModelFile storage, including bounded inbound writes,
  outbound chunk streaming, and no durable transferred-byte object.
- **2026-07-23** — v26. Clarified that only required file/blob cleanup can block Session purge; Git worktree state is outside the file-storage purge boundary.
- **2026-07-20** — v23. Unified attachment-bearing client and provider tool output as standalone deliveries that close ordered Activity without nested duplication.
- **2026-07-20** — v22. Promoted validated generated-image attachments to standalone Agent deliverables, preserved raw diagnostic ownership, and suppressed only duplicate nested image URIs.
- **2026-07-20** — v21. Extended attachment text previews to Markdown, common textual application media types, and safe UTF-8 files with unknown media types while excluding invalid UTF-8 and binary-control content.
- **2026-07-20** — v20. Added attachment preview navigation through gallery overflow, pointer and keyboard gestures, and modal-aware browser history behavior.
- **2026-07-19** — v19. Added atomic root-retention claims for ExchangeFile source/preview rows, same-tree access, archive preservation, and cleanup-before-cascade file purge semantics.
- **2026-07-19** — v18. Moved provider-generated Exchange attachments into canonical provider-call semantic output alongside ModelFile-backed replay parts.

- **2026-07-18** — v17. Reused generated-image dual materialization for xAI client tool results while preserving provider/client event ownership and Base64-free durable storage.
- **2026-07-17** — v16. Added provider-hosted generated-image dual materialization, retry-safe admission, request-local replay, and direct provider-tool attachment presentation.
- **2026-07-15** — v15. Required preallocated object keys, S3 upload outside DB sessions,
  ownership revalidation, and compensation cleanup before metadata becomes visible.
- **2026-07-15** — v14. Clarified that input-buffer promotion resolves only Exchange attachment
  metadata outside its locking transaction and reuses creation-boundary FileParts without download
  or rematerialization.
- **2026-07-11** — v13. Added persisted previews for uploaded text files and delegated original-image zooming to the browser's native image viewer.
- **2026-07-11** — v12. Clarified universal preview activation, isolated download actions, unsupported-file fallback, and original-only Agent image galleries.
- **2026-07-11** — v11. Documented compact attachment strips, Agent image galleries and mixed groups, dynamic overflow masks, and the shared responsive preview viewer.
- **2026-07-08** — v10. Documented subagent context-fork FilePart placeholder degradation and the no-blob-copy boundary.
