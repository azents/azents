---
title: "Direct File Transfer and Consistent File Limits Decisions"
created: 2026-09-29
tags: [files, runtime, chat, external-channel, transfer, architecture]
document_role: primary
document_type: adr
snapshot_id: files-260929
---

# Direct File Transfer and Consistent File Limits Decisions

- Snapshot: `files-260929`
- Requirements: [files-260929/REQ](../requirements/files-260929-direct-file-transfer.md)
- Document reference: `files-260929/ADR`

## Decision Status and Authority

The requester confirmed `files-260929/REQ` on 2026-09-29 after separately choosing each affected file path. The decisions below record those accepted choices. The requester retained ownership of material decisions; no blanket delegation or implementation approval was given.

The implemented [Runtime File Transfer ADR](transfer-260725-runtime-file-transfer.md) previously required all Runner file bytes to traverse Runtime Control and forbade Runner-visible presigned URLs. The later [Workspace Upload ADR](fileupload-260917-runtime-file-browser-upload.md) introduced a narrowly scoped Runner presigned GET exception. This snapshot extends exact-operation direct S3-compatible access to the file paths listed below. It supersedes the older no-presigned-URL and mandatory byte-relay boundaries **only for those paths**, while preserving the established authorization, generation fencing, integrity, atomic publication, cancellation, and cleanup authority. The [HTTP file download ADR](download-260917-runtime-http-file-download-streaming.md) remains historical evidence of the response-scoped API relay that this snapshot replaces for the two specified browser downloads. Implemented ADRs are not edited.

## Material Decision Map

- `files-260929/ADR-D1` — One general-purpose direct-transfer per-file limit of 128 MiB, with explicit independent semantic and provider constraints.
- `files-260929/ADR-D2` — Runner direct presigned GET for `import_file`, every stored part of `run_tool_to_file`, and `download_external_file` after authorized S3 staging.
- `files-260929/ADR-D3` — Runner direct presigned PUT for `present_file`, Runtime-source `channel_action`, `read_image`, and Workspace download preparation.
- `files-260929/ADR-D4` — Browser direct presigned PUT for Chat Exchange attachment ingress.
- `files-260929/ADR-D5` — Browser direct presigned GET for Workspace and Exchange downloads, with a bounded capability lifetime rather than application-observed exact HTTP body completion.
- `files-260929/ADR-D6` — Preserve feature-owned identities, model-input policy, provider limits, and per-part/per-file publication while changing only eligible complete-file transport.

Implementation-local protocol fields, helper boundaries, object names, and fixture composition are Design details, not additional requester decisions. Any new material authority or change to user-visible scope must return to the requester.

## Decisions

### `files-260929/ADR-D1`: Adopt one 128 MiB generic direct-transfer limit

**Authority:** `files-260929/REQ-1`, `REQ-3`, `REQ-4`, `REQ-6`; requester decisions on 2026-09-29.

The eligible general-purpose direct S3-compatible data paths in this snapshot share a per-file maximum of 128 MiB (134,217,728 bytes) without an additional lower Worker, API, or Runtime Transfer hop limit. `import_file`, `run_tool_to_file`, `present_file`, Chat attachment ingress, Workspace and Exchange downloads, and `download_external_file` must enforce the agreed product eligibility at their actual source, admission, and publication boundaries. External-channel inbound Runtime delivery deliberately decreases from its previously supported 500 MiB to 128 MiB; Exchange downloads of pre-existing objects over 128 MiB likewise become ineligible under the new direct-download policy. The rollout must measure any affected retained objects and existing admin settings before activation.

The 20 MiB `read_image` model-input-image limit remains a separate earlier semantic constraint. Existing target Tool output, provider upload, and external-channel outbound administrator limits also remain authoritative. A transfer is eligible only when it satisfies both the generic byte-path bound and its separate feature/provider policy. The shared default value may be reconsidered later; this decision does not add an admin setting or preapprove a different number.

**Rejected:** Changing the existing single Worker 8 MiB constant to 128 MiB without separating consumers would silently change image, external-provider, aggregate, and unrelated transfer policies. Leaving per-surface 8/20/64/128/500 MiB file limits would preserve the observed accept-then-reject failure. Keeping the 500 MiB inbound exception on the new direct path was rejected by the requester to retain one common generic number.

**Consequences:** Product configuration and any user-visible size diagnostics must agree on the effective boundary. Existing files and configured inbound limits may require an explicit rollout check; changing a previously supported product limit is intentional, not an accidental transport failure.

### `files-260929/ADR-D2`: Download S3-backed sources directly into Runner

**Authority:** `files-260929/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`; requester decisions on 2026-09-29.

`import_file` uses a short-lived presigned GET for its authorized `exchange://`, `artifact://`, and managed-file sources after staging an immutable verified object when necessary. `run_tool_to_file` applies the same S3-to-Runner direct GET to **every** saved output part, not only parts originally stored in S3; text, generated files, and ModelFile bytes are staged first under their existing source authority. `download_external_file` continues to authenticate and ingest provider bytes into a verified S3 staging object, then delivers that object directly to Runner by presigned GET at the new 128 MiB limit. Provider ingestion and Tool-owned byte production are not falsely described as direct-from-origin S3 uploads.

Reuse the implemented Workspace Upload trust principle: the queued Runner intent contains no URL; Runner claims the exact admitted active attempt through an authenticated control call before receiving a short-lived read-only object capability. Runner verifies exact size and SHA-256 while writing a temporary local file and performs only the authorized atomic destination commit. A presigned read alone never grants destination authority. This decision extends the existing direct-object transport to these feature sources without allowing a direct client-selected object key or long-lived Runner storage credentials.

**Rejected:** Keeping the Runtime Control download gRPC byte stream retains the redundant relay and its separate 8 MiB hop limit. Migrating only already-S3 `run_tool_to_file` parts leaves one Tool with inconsistent transfer capacity. Passing URLs in queued intents would retain bearer capabilities in ordinary coordination state.

**Consequences:** Trusted staging for byte-origin parts remains necessary and may already involve bounded feature-owned application bytes. Existing source expiry and Session/Run authority must remain valid through dispatch, and staged objects must have a bounded cleanup owner.

### `files-260929/ADR-D3`: Upload Runtime sources directly to verified storage

**Authority:** `files-260929/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`; requester decisions on 2026-09-29.

Runner sends eligible Runtime file bytes by an exact-attempt, short-lived presigned PUT to a private S3-compatible transfer target instead of streaming the body through Runtime Control. This applies to `present_file`, Runtime-path `channel_action` attachments, `read_image`, and the Runtime side of Workspace browser downloads. Runtime Control still owns authorization, current Runner generation, source path and size preflight, cancellation, attempt state, and result authority. Publication occurs only after the trusted server verifies the exact stored size and SHA-256 and captures an immutable source unaffected by outstanding write capability replay. The application does not treat a Runner success report, a PUT response alone, or mutable ingress object existence as publication authority.

`present_file` retains final Exchange publication; `channel_action` retains provider-native publication after verified staging without creating an Exchange attachment; `read_image` retains necessary server-side image normalization for model input; Workspace download retains requester-scoped file access. These feature-owned consumers do not gain a reusable S3 upload permission.

**Rejected:** Continuing Runner-to-Control gRPC byte uploads preserves duplicate bandwidth and the unrelated shared 8 MiB cap. Using a raw presigned PUT result as sufficient evidence would allow incomplete or rewritten content to be published. Reusing `present_file` to generate an Exchange attachment solely for outbound provider delivery changes resource identity and retention.

**Consequences:** Runner-side direct upload and trusted verified-finalize capabilities must be added to the Runtime Transfer contract. The S3 endpoint must remain reachable as authorized Platform transfer egress under supported network modes; checksum, overwrite/replay, cancellation, deadline, and object cleanup need deterministic verification.

### `files-260929/ADR-D4`: Upload Chat Exchange files directly from the browser

**Authority:** `files-260929/REQ-1`, `REQ-2`, `REQ-5`, `REQ-6`; requester decision on 2026-09-29.

Browser Chat attachment ingress uses a narrowly scoped presigned PUT into a private operation-owned S3 object, followed by authenticated finalize that verifies actual size and content integrity and publishes the existing Exchange attachment identity. The API never reads the complete upload body merely to relay it to storage. The initial upload alone is not a successful Exchange attachment; access, expiry, preview, retention, and Session-root claiming remain Exchange-owned after verified publication. The per-file upload maximum becomes 128 MiB.

This follows the security approach of Workspace Upload without incorrectly turning a Chat attachment into a Workspace file or granting the browser arbitrary S3 authority. Preparing the subsequent user message must not read an ineligible large original merely to discover that its distinct ModelFile/model-input policy cannot include the complete bytes.

**Rejected:** Raising the existing multipart API body limit to 128 MiB without changing its full-body read would amplify server memory and byte-relay cost. Reusing Workspace Upload product identity would mix Exchange retention and chat attachment authority with a temporary Runtime destination.

**Consequences:** Chat UI and public API need a coherent create/upload/finalize/error contract, and the normal message flow can use only finalized Exchange identities. Existing small-file model input behavior remains bounded independently from attachment acceptance.

### `files-260929/ADR-D5`: Serve browser downloads directly from private storage

**Authority:** `files-260929/REQ-1`, `REQ-2`, `REQ-5`; requester decisions on 2026-09-29.

For Agent Workspace downloads, Runner first uploads the exact authorized file under D3. For both Workspace and existing Exchange downloads, the API validates the requester and source, then issues a short-lived presigned GET for the verified private object and does not relay the HTTP body. The general-purpose direct-download limit is 128 MiB. Existing filename/media-type user behavior remains a product requirement, not an excuse to bypass access checks.

The current response-scoped API stream can observe exact body EOF and disconnect. A direct browser GET cannot provide that application-level completion signal. A transfer object needed for the presigned GET must therefore remain valid through a bounded ticket window and be cleaned by expiry or explicit ownership cleanup; issue of a URL is not recorded as completed download. Revocation after URL issuance has a bounded capability-lifetime window, and the signed URL is never placed in persisted transcript or application logs.

**Rejected:** Serving an S3 stream through the API preserves the intermediate application byte relay and the Workspace 64 MiB boundary. Pretending a URL issue means successful complete browser download would produce false completion and premature temporary-object cleanup. Retaining a permanent public Exchange URL would circumvent requester authorization and expiry.

**Consequences:** Existing streaming-response completion semantics change only for these browser endpoints. The endpoint protocol and browser handling must account for a short-lived bearer URL, private-object existence and lifetime, safe content disposition, and failed or interrupted GETs without server-observed byte completion.

### `files-260929/ADR-D6`: Preserve feature policies and product resource ownership

**Authority:** `files-260929/REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`; requester decisions on 2026-09-29.

A source's product ownership and policy remain with the feature that produced it. `import_file` retains its scheme and destination behavior; `run_tool_to_file` retains one target execution with partial part-level success and manifest semantics; `present_file` retains verified Exchange publication; `read_image` retains its 20 MiB image rule and model normalization; and externally sourced file bytes retain provider authorization and integrity checks. Outbound External Channel administrator, provider, and action-aggregate limits are not raised by the internal 128 MiB transfer capacity. Chat Exchange attachments remain usable for authorized Runtime import and download even if their full body is not eligible as inline model input.

**Rejected:** Applying 128 MiB indiscriminately to image/model, external-provider, or text/console limits would conflate distinct user actions and violate explicit requester exceptions. Creating duplicate Exchange resources merely to implement transient Runtime-to-provider delivery would change retention and visibility.

**Consequences:** Policy evaluation must identify whether a failure is a common transfer bound or a feature-owned bound. The previously shared 8 MiB Worker constant cannot remain a single knob controlling all of these feature services.

## Open Design and Verification Obligations

The Design must establish exact-attempt presigned upload and download mechanics, trusted checksum and immutable-snapshot evidence, endpoint reachability and network-policy feasibility, retry/cancellation/cleanup behavior, large Chat attachment promotion safety, public API and browser contract changes, existing-object/configuration rollout, and E2E verification. It must not introduce a second material transport mode, silently restore a >128 MiB generic path, or claim that an external provider or model-input limit has been raised.
