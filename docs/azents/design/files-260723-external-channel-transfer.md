---
title: "External Channel File Transfer Design"
created: 2026-07-23
updated: 2026-07-23
implemented: 2026-07-23
tags: [slack, external-channel, files, runtime, delivery, system-settings]
document_role: primary
document_type: design
snapshot_id: files-260723
---

# External Channel File Transfer Design

- Snapshot: `files-260723`
- Document reference: `files-260723/DESIGN`
- Requirements: [`files-260723/REQ`](../requirements/files-260723-external-channel-transfer.md)
- ADR: [`files-260723/ADR`](../adr/files-260723-external-channel-transfer.md)

## Overview

This design adds provider-neutral file transfer to the explicit External Channel
conversation boundary, with Slack as the first adapter.

Inbound Slack messages retain bounded file metadata but do not download file content,
create Exchange files, or create ModelFiles. Agent-visible metadata includes one
provider-neutral locator for each observed file. A root Agent explicitly invokes a
download tool with that locator and a Runtime destination path. Azents verifies the
current active binding and connection, then delegates file visibility to Slack and writes
the bounded response bytes to the Runtime.

Outbound delivery extends the existing `channel_action` input with Runtime file paths.
The action validates all paths and sizes before commit, records one combined delivery
intent, and then streams each file from the Runtime to Slack in bounded chunks. After all
file streams succeed, one Slack completion publishes the conversational text and every
file together in the bound root thread. No Exchange, Artifact, or private staging object
is created.

## Traceability

| Requirement | ADR decisions | Primary design mechanisms |
| --- | --- | --- |
| `files-260723/REQ-1` | `files-260723/ADR-D2` | Bounded Slack `files[]` projection, revision metadata, model-visible file locator |
| `files-260723/REQ-2` | `files-260723/ADR-D1`, `files-260723/ADR-D2` | Root-only explicit download tool, provider lookup, bounded Runtime write |
| `files-260723/REQ-3` | `files-260723/ADR-D1`, `files-260723/ADR-D2` | Active Agent/Session/binding/connection validation and provider-authoritative access |
| `files-260723/REQ-4` | `files-260723/ADR-D1`, `files-260723/ADR-D2` | Slack file-mode classification and fail-closed download validation |
| `files-260723/REQ-5` | `files-260723/ADR-D3`, `files-260723/ADR-D5` | Typed global limits, pre-commit stat validation, actual-byte enforcement |
| `files-260723/REQ-6` | `files-260723/ADR-D3`, `files-260723/ADR-D4` | `channel_action.files`, sequential Runtime streaming, one Slack completion and outcome |
| `files-260723/REQ-7` | `files-260723/ADR-D1`, `files-260723/ADR-D2`, `files-260723/ADR-D5` | Provider-neutral capabilities, locator envelope, Tool and settings contracts |

## Current Behavior and Gaps

### Inbound

- `slack_http.py::_project_envelope` and `_project_slack_message` omit Slack
  `files[]`.
- `SlackNormalizedMessage.attachment_metadata` currently summarizes Block Kit only.
- External message revisions already persist nullable JSONB `attachment_metadata`.
- `ExternalChannelInvocationInputBufferProcessor` moves that metadata into
  `ExternalChannelMessagePayload`.
- External input intentionally creates no attachments or FileParts and downloads no
  provider bytes.

The reusable boundary is therefore the existing revision metadata path. The gap is a
bounded file projection and an explicit Runtime materialization tool.

### Outbound

- `FinishChannelActionInput` and `ContinueChannelActionInput` accept text and Channel
  Work data but no Runtime files.
- `commit_action` creates one durable `REPLY` intent for conversational text.
- Slack delivery supports JSON message operations only.
- Runtime file storage can stat a file and read a bounded range through the Runner
  protocol, but the common `FileStorage.get()` API materializes the complete file.
- The current delivery contract commits before provider mutation and never blindly
  retries an ambiguous result.

The reusable boundary is the existing `REPLY` delivery intent and outcome ledger. The
gap is a streaming file source and Slack external-upload lowering.

## Provider-Neutral File Metadata

### Stored revision metadata

Slack normalization extends revision `attachment_metadata` with a bounded `files` list.
Each entry stores only values required for display and later provider access:

```json
{
  "files": [
    {
      "provider": "slack",
      "provider_file_id": "F...",
      "name": "report.csv",
      "title": "Report",
      "media_type": "text/csv",
      "declared_size": 1024,
      "mode": "hosted",
      "external": false,
      "file_access": null,
      "supported": true,
      "unsupported_reason": null
    }
  ],
  "blocks": {
    "block_count": 2,
    "block_types": ["section", "context"],
    "truncated": false
  }
}
```

The projection retains at most 20 files and bounded strings. It never retains a private
download URL, bearer token, thumbnail URL, arbitrary provider object, or file body.
Unsupported entries remain visible with a stable reason instead of rejecting the complete
message.

No attachment table is added. Provider event and hydration paths use the same normalized
shape so a file has the same metadata whether observed through Events API admission or
`conversations.replies`.

Slack HTTP projection must retain bounded `files[]` for both top-level message events and
nested `message`/`previous_message` variants. Socket admission uses the same projected
envelope contract, and hydration projects the same fields from
`conversations.replies`. Normalization reads file metadata independently from Block Kit
metadata so block-only, file-only, and mixed messages remain valid.

### Agent-visible locator

When an invocation batch is projected, each file receives a deterministic versioned
locator containing the current binding identity and provider file identity:

```text
external-file:v1:slack:<binding-id>:<provider-file-id>
```

The exact delimiter and parser are implementation details, but the envelope remains
provider-neutral and versioned. It is neither encrypted nor signed. The Agent passes the
complete value back without supplying provider fields separately.

The locator is a request address, not authorization. An altered file identity may select
another file visible to the same Slack App, as accepted by `files-260723/ADR-D2`.

### Model and continuity rendering

Persisting `attachment_metadata` is insufficient because the model-facing Responses
lowerer and continuity filters use text renderers rather than the structured visible
value. Extend both `render_external_channel_message()` and
`render_external_channel_turn()` with one deterministic bounded `Files:` section. Each
entry includes filename/title, media type, declared size, supported state or rejection
reason, and the complete locator.

Use the same rendering helper for:

- first-turn Responses input;
- replayed External Channel messages;
- compaction and Recent Transcript continuity text; and
- token estimation/model-visible value accounting.

The structured `external_channel_message_visible_value()` retains the same semantic
fields for Web/event projection. Tests must prove that initial input, resumed input,
compaction continuity, and token accounting all observe the same bounded file list and
that no private URL or file body enters any representation.

## Inbound Download Tool

### Tool contract

The root External Channel Toolkit exposes a second tool while at least one active binding
exists:

```text
download_external_file(
  file: <opaque locator>,
  path: <absolute Runtime path>,
  overwrite: false
)
```

One call handles exactly one file. `overwrite` follows the existing Runtime file-tool
policy: an existing destination fails unless overwrite is explicitly enabled.

The Tool result reports the Runtime path, provider-reported filename, media type, and
actual byte count. It never returns provider credentials or a private download URL.

### Authorization and provider flow

1. Parse the locator version, provider, binding ID, and provider file ID.
2. Lock or read the referenced binding through the current Agent and Session scope.
3. Require the Agent, Session, binding, route, and connection to remain active.
4. Require the connection capability `download_files`.
5. Decrypt the stored connection credential outside model-visible state.
6. Call Slack `files.info` for the requested provider file ID.
7. Reject external/remote files, Slack Connect access-check files, deleted or inaccessible
   files, unsupported modes, and declared oversize.
8. Prefer `url_private_download` when present; otherwise use `url_private`, and fetch the
   selected current private URL with the stored bearer token.
9. Enforce the configured actual-byte limit while reading the response.
10. Write the complete bounded payload through Runtime `FileStorage.put`.

The first release keeps inbound Runtime writes whole-buffered because the current Runner
write contract accepts one `bytes` payload. The 25 MiB default and configured hard limit
bound this memory use. A future chunked Runtime write is outside this snapshot.

Slack is authoritative for whether its App credential may access the requested file.
Azents does not re-prove that the file ID still belongs to the message revision where the
locator was first presented.

### Failure handling

- An inactive or unrelated binding fails before a provider request.
- Missing `files:read` capability returns a controlled capability error without
  disconnecting text conversation.
- Provider denial, missing/deleted file, unsupported mode, and size rejection are
  controlled Tool failures.
- A network or provider temporary failure does not write a partial Runtime file.
- A destination write failure reports failure even when provider download completed.
- No Exchange or ModelFile compensation is required because neither resource is created.

## Outbound Channel Publication

### Tool input

Both `finish` and `continue` variants add:

```text
files: [<absolute Runtime path>, ...]
```

The list is optional and contains at most 20 paths. A file-bearing publication requires
conversational `message` text, so files are always part of one explicit reply rather than
an upload-only action. Text-only calls preserve the existing behavior.

Before `commit_action`, the Tool obtains Runtime file metadata without reading the complete
body. It requires regular readable files, derives the provider filename from the Runtime
basename, detects the media type, and applies:

- configured outbound per-file maximum;
- configured outbound aggregate maximum; and
- provider-specific preflight constraints known before upload.

The action request and `REPLY` delivery payload persist a file manifest containing Runtime
path, filename, media type, and expected size. They never persist file bytes, Base64,
Exchange URIs, Slack upload URLs, or bearer tokens.

### Runtime chunk source

Add a bounded chunk-reading API beside `FileStorage.get()`. The Runtime Runner protocol
already supports `offset` and `max_bytes`, so the implementation repeatedly requests a
1 MiB internal chunk and yields each result to the Slack HTTP client.

The streaming source:

- reads one file at a time;
- never joins all chunks;
- counts actual bytes;
- stops when the expected size is reached;
- fails if the Runtime returns too few or too many bytes; and
- does not attempt to resume from an interrupted offset.

The first release does not hold one Runtime file descriptor open across the complete
upload. A same-size concurrent file mutation may therefore change bytes without detection.
This is an accepted non-blocking risk under the one-attempt contract.

### Run-scoped Runtime dependency

`RuntimeRunnerFileStorage` is created per run and is not a process-wide dependency of
`ExternalChannelActionService`. Extend the existing shared
`RuntimeInstructionContextStore` so the External Channel Toolkit obtains the current
run-scoped `FileStorage` at Tool-call time.

The Toolkit uses that storage for download destination writes and outbound preflight. It
passes a run-scoped file source into `ExternalChannelActionService.execute` for the
immediate post-commit attempt. Text-only, cleanup, and management delivery paths do not
require this source. A recovered file-bearing delivery without its original run-scoped
source is not replayed; existing stale-attempt handling terminalizes it conservatively.

### Slack file-bearing reply

One committed file-bearing `REPLY` executes these provider steps:

1. For each manifest entry in order, call `files.getUploadURLExternal` with filename and
   expected length.
2. Stream the Runtime file to the returned upload URL with a known content length.
3. Retain only the returned temporary provider file ID and bounded phase evidence.
4. If any acquisition or stream fails, stop and do not publish the reply.
5. After every stream succeeds, call `files.completeUploadExternal` once with the ordered
   file IDs, bound channel, root `thread_ts`, and conversational text.

The Slack completion is the sole provider-visible publication boundary. A confirmed
completion marks the existing `REPLY` delivery delivered. A confirmed pre-completion
rejection marks it failed. Transport ambiguity during an upload or completion marks the
complete reply unknown. No upload or completion step is automatically replayed.

The delivery remains one `ExternalChannelDeliveryOperation.REPLY`; no file-specific
delivery enum or separate model-visible action is introduced. Phase information needed
for diagnostics is stored inside the delivery request/result metadata rather than as
independent delivery outcomes.

## Connection Capabilities and Slack Setup

Extend `ExternalChannelCapabilitySnapshot` with independent provider-neutral booleans:

- `download_files`
- `upload_files`

Slack validation maps `files:read` to `download_files` and `files:write` to
`upload_files`. Missing or unavailable scope evidence does not grant a capability, but it
does not invalidate the unrelated text connection. Provider operations remain
authoritative and map a later Slack `missing_scope` response to a controlled failed
outcome.

Generated Slack App guidance requests both scopes for new installations. Existing Apps
remain active for text conversation and gain each file direction after the corresponding
scope is installed and the connection is validated again.

## System Settings and Admin Management

Add `external_channel_files` to the compiled `SystemSettingSection` enum and PostgreSQL
enum through a new migration. Register a schema-version-1 direct-activation definition
with no secret fields:

```text
inbound_max_file_bytes = 26_214_400
outbound_max_file_bytes = 26_214_400
outbound_max_action_bytes = 104_857_600
```

The aggregate default is 100 MiB and must be at least the per-file default. All values are
positive, bounded integers. Runtime stream chunk size remains an internal constant.

The generic settings repository, audit metadata, version conflict handling, and effective
generation are reused. Add a dedicated Admin API representation and an
`External Channel files` card to Admin Web System Settings. The card uses MiB inputs,
shows the effective byte values and version, and performs direct save with the normal
audit trail. It has no candidate validation or health-check workflow because the values
are local policy only.

Admin OpenAPI and the generated Admin TypeScript client must be regenerated through the
existing generators.

## Persistence, API, and Migration Impact

### Required migration

- Add `external_channel_files` to PostgreSQL enum `system_setting_section`.

### No new domain table

- No attachment entity.
- No Exchange, Artifact, or ModelFile row for inbound or outbound Channel transfer.
- Existing external-message revision JSONB stores bounded file metadata.
- Existing connection capability JSONB stores new capability fields.
- Existing action and delivery JSONB stores outbound manifests and phase evidence.
- Existing `REPLY` enum value owns file-bearing outcomes.

### Internal contracts

- Slack event projection and normalization gain bounded file models.
- `ExternalChannelMessagePayload` exposes normalized file metadata and locators.
- External Channel Toolkit gains the download tool and `channel_action.files`.
- Runtime file storage gains bounded chunk iteration.
- Slack conversation client gains file-info, private download, upload-URL streaming, and
  completion operations.
- System Settings gains one typed section and runtime resolver.

No public Main Web file-upload API is added. Admin API/client changes are required for
limit management.

## Security and Privacy

- Slack credentials and private file URLs remain server-only and are never persisted in
  message metadata, Tool input/output, delivery payloads, or logs.
- The current Agent and Session must own the active binding named by a download locator or
  publication action.
- Provider authorization is the file visibility boundary; file locators are intentionally
  not cryptographic capabilities.
- Runtime destination and source paths use existing path normalization and ownership.
- Inbound actual bytes and outbound stat sizes are checked against effective limits.
- Logs retain only bounded provider error codes, file counts, sizes, phases, and Azents
  entity IDs. They omit filenames when not needed for diagnosis and never include file
  content.
- Provider URLs are consumed only from authenticated Slack API responses and are not
  accepted from Tool input.

## Lifecycle

- A locator remains usable across turns while its referenced binding and connection are
  active and Slack permits access.
- Binding disconnect, connection disconnect, Session archive, and Agent decommission
  immediately prevent new downloads and file publications through existing lifecycle
  fencing.
- Revoked credentials remove file capabilities or make the provider operation fail.
- Slack deletion or access removal is observed at download time.
- In-progress outbound delivery follows the existing one-attempt provider outcome; a
  lifecycle transition does not replay an interrupted upload.
- No new file retention or purge participant is required because Azents stores no Channel
  transfer bytes.

## Observability

Add bounded metrics and structured logs for:

- inbound attachment count and supported/unsupported classification;
- download request, bytes, latency, and failure kind;
- outbound file count, declared bytes, streamed bytes, and phase;
- capability availability by connection;
- provider rejection, rate limit, transport ambiguity, and Runtime read/write failure;
- limit rejection by direction and policy generation.

Delivery management continues to show the combined `REPLY` status. File-bearing attempts
add a bounded summary such as file count and last completed phase without exposing URLs,
credentials, or content.

## Test Strategy

### Unit and service tests

- HTTP and Socket projections retain identical bounded `files[]` metadata.
- Normalization handles multiple direct uploads and marks external, Slack Connect, sparse,
  malformed, and truncated records unsupported.
- Invocation projection produces deterministic binding-scoped locators.
- Text and structured External Channel renderers expose the same bounded metadata and
  locator list through first-turn lowering, replay, filters, compaction continuity, and
  token accounting.
- Download Tool validates active ownership, capabilities, provider access, declared and
  actual size, overwrite policy, and Runtime write failure.
- A modified provider file ID is passed to Slack under the same active binding, and Slack
  remains the authoritative allow/deny result.
- Connection validation independently reports download and upload capabilities.
- Runtime chunk iteration never calls whole-file `get()` and preserves ordered bytes.
- Outbound preflight enforces per-file and aggregate settings.
- Multi-file upload streams sequentially, skips completion after any failed stream,
  completes once after all streams, and maps ambiguous completion to one unknown reply.
- System Settings migration, definition, direct mutation, audit, runtime resolution, and
  Admin API serialization are covered.

### Deterministic E2E

Extend the Slack provider fake with:

- `files.info`;
- authenticated private download bodies;
- `files.getUploadURLExternal`;
- upload URL byte collection without whole-body application fixtures;
- `files.completeUploadExternal`; and
- configurable scope, provider rejection, missing file, size mismatch, and ambiguous
  completion outcomes.

The primary journey:

1. sends one Slack invocation containing multiple direct-upload file metadata entries;
2. confirms the Agent receives bounded metadata and locators without file bytes;
3. observes one explicit download Tool call and the expected Runtime destination;
4. verifies the Agent processes the selected file only;
5. observes one file-bearing `channel_action`;
6. verifies ordered chunk upload for multiple Runtime files; and
7. verifies one completion publishes text and all files to the original root thread.

Testenv fixtures use public/provider behavior and do not write External Channel database
state directly.

### Quality checks

- Python: focused Ruff, Pyright, service/unit tests, migration test, and deterministic
  E2E.
- TypeScript: generated Admin client, format, lint, typecheck, Admin Web tests, and build.
- Do not run TypeScript lint, typecheck, and build concurrently.

## Rollout and Rollback

- Deploy the enum migration before code that resolves the new settings section.
- Existing connection capability JSON remains readable; missing file fields default to
  unavailable.
- Existing Slack Apps remain text-capable. New manifest guidance requests file scopes.
- Existing messages without file metadata render unchanged.
- File-bearing Tool inputs are additive and old text-only delivery remains unchanged.
- Rolling back application code leaves only an unused System Settings enum value and
  additive JSON fields. No Channel file bytes or attachment rows require cleanup.

## Implementation Shape

This feature crosses provider ingress, Engine Tooling, Runtime I/O, delivery, System
Settings, Admin Web, and E2E. Use a stacked implementation rather than one oversized PR:

1. bounded inbound metadata, capabilities, settings migration, and contracts;
2. explicit inbound download Tool and Slack read adapter;
3. outbound `channel_action.files`, Runtime chunk source, and one-outcome Slack delivery;
4. Admin settings surface, fake provider, deterministic E2E, and living-spec updates.

Create the complete stack before monitoring CI. Do not merge any PR without explicit
requester approval for that merge.

## Living Spec Impact

After implementation, update and verify:

- `docs/azents/spec/domain/external-channel.md`;
- `docs/azents/spec/flow/external-channel-provider-ingress.md`;
- `docs/azents/spec/flow/external-channel-delivery.md`;
- `docs/azents/spec/flow/external-channel-lifecycle.md`;
- `docs/azents/spec/flow/file-exchange-storage.md`; and
- `docs/azents/spec/flow/agent-execution-loop.md`.

The file-storage spec must explicitly distinguish Channel transfer from Exchange,
Artifact, and ModelFile materialization.

## Feasibility Validation

No requirement or accepted ADR decision is blocked.

| Requirement | Result | Repository evidence and required extension |
| --- | --- | --- |
| `files-260723/REQ-1` | feasible | Slack projection already performs bounded allowlisting; revision JSONB and `ExternalChannelMessagePayload.attachment_metadata` provide the persistence path. Add bounded top-level/nested `files[]` fields plus explicit turn/message text rendering, filters, continuity, token-accounting, and lowerer tests so the locator reaches the model. |
| `files-260723/REQ-2` | feasible | The External Channel Toolkit is root-only and active-binding scoped; Slack HTTP and Runtime `FileStorage.put` exist. Add the download Tool, provider read calls, and bounded whole-buffer write. |
| `files-260723/REQ-3` | feasible | Binding, route, connection, Agent, and Session active-state joins already fence `channel_action`. Reuse the same ownership check and delegate final file access to Slack. |
| `files-260723/REQ-4` | feasible | Slack normalization already rejects Slack Connect conversations and has provider error mapping. File object mode/access classification is an additive bounded adapter rule. |
| `files-260723/REQ-5` | feasible | Typed versioned System Settings, Admin audit, and PostgreSQL enum migrations already exist. Add one section, Admin surface, and provider/runtime limit checks. |
| `files-260723/REQ-6` | feasible | `channel_action` already commits one `REPLY` before provider mutation; Runtime read supports offset/max-bytes; Slack external upload supports multiple files in one completion. Extend the payload and adapter without a new delivery table or enum. |
| `files-260723/REQ-7` | feasible | Capabilities and revision/action payloads are provider-neutral JSON models. The locator, settings section, Tool schema, and provider adapter preserve that boundary. |

### Non-blocking risks

- Inbound Runtime writes remain whole-buffered up to the configured limit.
- Outbound same-size Runtime mutation during streaming is not detected.
- Slack may return an ambiguous completion without a convenient reply timestamp; the
  delivery can remain correctly `unknown` without a provider message key.
- Existing connections need reinstallation before each missing file capability becomes
  available.
- Admin System Settings UI is currently GitHub-App-specific and requires decomposition to
  add the file-limit card cleanly.
