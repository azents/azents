---
title: "Provider-Hosted Image Generation Restoration"
created: 2026-07-17
updated: 2026-07-17
tags: [backend, engine, frontend, llm, storage, tools, testenv, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: hosted-260717
migration_source: "docs/azents/design/provider-hosted-image-generation.md"
historical_reconstruction: true
---

# Provider-Hosted Image Generation Restoration

## Problem

Azents has canonical parsing and UI support for provider-hosted `image_generation` activity, but the configurable builtin was removed because request lowering, capability projection, and output materialization were incomplete. The remaining output path replaces a completed image with an unavailable placeholder attachment.

Restoring only the configuration registry would recreate the original drift: a selected builtin could be silently omitted by a lowerer, and a completed provider result would still not produce a usable file.

## Goals

- Restore the semantic `image_generation` builtin in one change across OpenAI SDK, ChatGPT OAuth, and LiteLLM.
- Keep provider-specific wire syntax inside adapter lowerers and normalizers.
- Keep raw Base64 and image bytes out of durable events, database payload columns, REST/WebSocket projections, frontend state, logs, and native artifacts.
- Expose each generated image to later model calls as a ModelFile-backed `FileOutputPart`.
- Expose the same generated image to the user as an Exchange-backed Attachment.
- Preserve provider-tool live activity and canonical terminal status.
- Fail explicitly when the selected model or lowerer cannot provide the shared semantic behavior.

## Non-Goals

- Restoring the historical Gemini Shell, reasoning, toolkit, Agent-role, or subagent validation conditions.
- Reintroducing Agent-global builtin settings.
- Treating generic image output modality as proof of provider-hosted image-tool support.
- Persisting provider-native image payloads for exact replay.
- Creating a compatibility path that silently drops unsupported builtins.
- Adding a new public event or attachment schema when the existing `FileOutputPart` and `Attachment` contracts are sufficient.

## Current Behavior

- `BuiltinToolSpec` already allows `image_generation` semantically.
- OpenAI SDK and LiteLLM normalizers recognize `image_generation_call` and provider-tool live states.
- The native artifact sanitizer removes the `result` field before persistence.
- The current result event contains an unavailable `generated-image:` attachment with size zero.
- `LiteLLMResponsesLowerer` dispatches only `web_search` and silently skips every other builtin.
- ModelFile request-local materialization already turns durable FileParts into provider request content.
- Provider-tool result attachments already reach the frontend projection, but generated images are not backed by Exchange storage.

## Proposed Design

### 1. Restore one semantic builtin contract

Add `image_generation` to the implemented builtin registry. The registry entry has no historical Gemini-specific rule. Generic model-option validation verifies that the selected model snapshot advertises `image_generation`.

All hosted-tool dispatch becomes exhaustive:

- `web_search` uses the existing translation;
- `image_generation` uses the image-generation translation;
- any registered semantic builtin without a lowerer implementation raises `UnsupportedRequiredBuiltinToolError`;
- any selected builtin missing from the selected model capability raises before provider dispatch.

The semantic config remains an open JSON object whose accepted keys are provider-contract fields such as quality, size, format, background, or partial image count. Each lowerer passes only fields accepted by its native target validation. Invalid config fails preparation rather than being removed.

### 2. Lower through every supported runtime path

#### OpenAI SDK

`OpenAIResponsesLowerer` emits:

```json
{"type": "image_generation", "...config": "..."}
```

The request is validated by the installed OpenAI SDK `ToolParam` adapter before dispatch.

#### ChatGPT OAuth

ChatGPT OAuth continues to use `OpenAIResponsesLowerer` and the standard Responses request shape. It receives dedicated tests because it uses different credentials, headers, base URL, and `store=false` continuation behavior.

#### LiteLLM

`LiteLLMResponsesLowerer` emits the same Responses semantic tool shape and passes it to LiteLLM without converting it into a function tool. LiteLLM owns provider-dialect translation after Azents has enforced the model capability boundary.

Azents does not advertise `image_generation` for a LiteLLM-routed model merely because its generic output modalities contain `image`. Capability projection requires an explicit trusted source flag or an Azents-owned provider/model capability override.

### 3. Separate canonical events from transient image bytes

Add a provider-neutral transient output type, conceptually:

```python
class PendingProviderFileOutput(BaseModel):
    call_id: str
    tool_name: Literal["image_generation"]
    filename: str
    media_type: str
    body: bytes = Field(exclude=True, repr=False)
```

`NormalizedAdapterOutput` carries these pending outputs in an excluded transient field. The field is never accepted by event repository APIs and is omitted by `model_dump()`.

Adapter-local parsing performs only native extraction:

- OpenAI SDK reads the typed `image_generation_call.result`;
- LiteLLM reads the normalized response item or supported image result shape;
- data-URL prefix removal, when required by a provider dialect, stays adapter-local.

A shared decoder then:

1. rejects an encoded value above the pre-decode bound;
2. performs strict Base64 decoding;
3. enforces a 20 MiB decoded-image limit;
4. verifies that the bytes are a supported image and detects the actual media type;
5. computes SHA-256 for diagnostics and deterministic preparation metadata.

No raw encoded value or decoded bytes are placed in the canonical provider-tool event skeleton.

### 4. Materialize before durable output admission

Introduce a shared `ProviderOutputMaterializer` at the Engine boundary. It runs after the adapter stream has completed successfully and before `_has_durable_model_output` and durable append.

For each pending generated image it prepares:

- an Exchange file containing the original validated provider bytes;
- the normal Exchange preview thumbnail metadata;
- a ModelFile containing bytes normalized by the existing ModelFile image policy;
- an updated `ProviderToolResultPayload` referencing both resources.

The updated event uses:

```text
provider_tool_result
├── output
│   └── FileOutputPart(model_file_id=..., kind="image", ...)
└── attachments
    └── Attachment(attachment_id=..., uri="exchange://...", source="provider_tool", ...)
```

The `FileOutputPart` metadata records bounded provenance only:

- `source_kind=provider_tool`;
- `source_tool_name=image_generation`;
- `source_call_id`;
- optional source media type and SHA-256.

The Attachment preserves the provider image media type and original bytes. The ModelFile may use normalized JPEG bytes and therefore has independent media type, size, hash, lifecycle, and storage key.

### 5. Commit metadata and event references together

The materializer uses a prepared-output admission pattern:

1. Validate Session, Agent, Workspace, and actor ownership in a short database session.
2. Preallocate ExchangeFile and ModelFile IDs and object keys.
3. Prepare the Exchange preview and normalized ModelFile bytes in memory.
4. Upload the Exchange original, preview if present, and ModelFile object without holding a database transaction.
5. Enter the existing model-output append transaction.
6. Revalidate ownership and persist all prepared file metadata.
7. Append the updated provider-tool result and remaining normalized events.
8. Append the turn marker and clear retry state through the existing successful-output transaction.
9. If steps 5-8 fail, compensation-delete every prepared object.

No completed provider-tool result is committed unless both the Exchange and ModelFile metadata are committed in the same transaction as the event reference.

The prepared object keys include run, call, and output-index identity. Repeated admission inside the same model attempt is idempotent. Object-storage lifecycle cleanup covers the narrow process-crash window between upload and database admission.

### 6. Expose the FilePart to later model calls

The durable provider-tool result remains in the transcript and its `FileOutputPart` participates in `unique_model_file_ids()`, ModelFile pinning, pre-lower availability filtering, and request-local materialization.

#### Compatible Responses replay

When the event native artifact is compatible with the target adapter, the lowerer reconstructs `image_generation_call.result` only in the request-local native item. It resolves the ModelFile, converts its normalized bytes to plain Base64, and adds that value to a copy of the sanitized native item.

The persistent native artifact remains sanitized. The reconstructed item exists only for the duration of the outbound request.

`ResponsesContinuationPlanner` compares sanitized request items with sanitized recorded output items. A request-local reconstructed `result` therefore does not disable `previous_response_id` continuation, and a continuation delta does not resend the image when the provider already retains the prior response.

ChatGPT OAuth uses `store=false`, so it sends the request-local reconstructed result in the full request.

#### Cross-adapter or incompatible replay

If the native artifact is incompatible, the lowerer emits a synthetic model-input message containing:

- a bounded text marker identifying the prior provider-tool result; and
- the shared `FileOutputPart` lowered through `lower_file_output_part()`.

A model with image-input capability receives `input_image`. A model without it receives the existing explicit bounded placeholder. No lowerer silently removes the file.

The image-generation capability contract should normally be advertised only on models that can also consume image input, ensuring the generating model can observe its own output on a later turn.

### 7. Do not force an extra model turn

A completed image-generation result does not by itself synthesize another model call. If the provider explicitly returns `end_turn=false`, the existing follow-up behavior runs and the image is present in that next request. Otherwise the run may complete with the image attachment, and the FilePart becomes available on the next user-initiated turn.

### 8. Expose the attachment directly in Chat UI

History and live projection continue to merge provider call and result by `call_id`. The completed tool card receives the Exchange-backed attachment.

Generated image attachments render directly below the provider-tool header when available; arguments and text diagnostics remain in the expandable details section. Preview and download use the existing Exchange attachment viewer and download endpoint. Expired or unavailable history uses the existing attachment availability states.

No frontend component receives Base64, a data URL, or a `generated-image:` placeholder URI.

## Failure Handling

### Provider payload failures

The following are non-successful model outputs:

- missing final image result;
- invalid Base64;
- encoded or decoded size limit violation;
- unsupported or corrupt image bytes;
- call identity collision inside one completed response.

The Engine does not append a completed provider-tool result for these cases. The failure propagates through the existing model-call failure boundary with a bounded user-safe message and without raw payload content.

### Storage failures

Transient object-storage operations may retry locally with the same in-memory bytes and a bounded backoff. If preparation or admission still fails:

- no event reference is appended;
- prepared objects are compensation-deleted when possible;
- the run failure/retry boundary receives a storage materialization error;
- logs contain IDs, sizes, media types, and hashes, never image bytes or Base64.

### Partial materialization

Creating only an Attachment or only a ModelFile is not successful output. The coordinator compensates prepared resources and fails admission. The UI and model therefore cannot observe different success states for the same generated image.

## Capability and Migration Policy

### Capability projection

Restore `image_generation` in the implemented configurable registry, then project it only from trusted provider/model support information.

- OpenAI system catalog uses explicit model capability metadata or curated overrides.
- ChatGPT OAuth projection uses an explicit account-visible model capability policy, covered by fixture snapshots.
- LiteLLM-routed entries require an explicit source flag or curated override; `supported_output_modalities=image` alone is insufficient.

The lowerer still validates capability at runtime so stale snapshots cannot cause silent omission.

### Forward migration

Create a new Alembic revision; do not modify an executed migration.

The migration updates stored capability snapshots for models covered by the restored support matrix, including current catalog entries and embedded Agent, Workspace, and Session model-selection snapshots where required by current model-scoped settings semantics.

Existing `settings.builtin_tools` lists remain unchanged. Existing options therefore keep their current opt-in state. New or newly selected options follow the current defaulting contract and enable every supported implemented builtin when builtin intent is omitted.

No data migration attempts to reconstruct historical `image_generation` intent removed by the earlier model-scoped migration.

## Security and Resource Controls

- Decoded image size is bounded before storage.
- Encoded length is bounded before Base64 allocation.
- Image verification uses the shared safe image path and rejects corrupt input.
- Session, Agent, Workspace, and actor ownership are validated before upload and revalidated before metadata admission.
- File names are generated or sanitized; provider text never becomes an object key.
- Native artifacts and errors are sanitized before logging or persistence.
- Exchange and ModelFile lifecycle policies remain independent.
- ModelFile request rehydration occurs only after normal Agent/user authorization checks.

## Affected Areas

### Backend and Engine

- builtin tool registry and model-option validation;
- model catalog capability projection and ChatGPT listing projection;
- OpenAI/LiteLLM hosted-tool lowering;
- OpenAI/LiteLLM output normalization;
- transient normalized output contract;
- provider output materialization and prepared admission;
- ModelFile request-local rehydration;
- Responses continuation comparison;
- provider-tool result projection.

### Database

- forward migration for stored capability snapshots;
- no event payload column or schema addition for image bodies;
- no public API schema addition is expected;
- a generated origin enum is unnecessary if the current Exchange artifact origin remains the storage classification and `Attachment.source="provider_tool"` carries presentation provenance.

### Frontend

- provider tool card direct generated-image rendering;
- existing attachment viewer/download and unavailable states are reused.

### Specs

Implementation updates should revise at least:

- `docs/azents/spec/domain/model-catalog.md`;
- `docs/azents/spec/domain/agent.md`;
- `docs/azents/spec/domain/conversation.md`;
- `docs/azents/spec/flow/agent-execution-loop.md`;
- `docs/azents/spec/flow/file-exchange-storage.md`.

## Test Strategy

### Primary deterministic E2E matrix

Run one semantic scenario through each supported runtime path:

| Runtime path | Tool request | Live lifecycle | Durable result | Model reuse | User attachment |
| --- | --- | --- | --- | --- | --- |
| OpenAI SDK | required | required | required | required | required |
| ChatGPT OAuth | required | required | required | required with `store=false` | required |
| LiteLLM | required | required | required | required | required |

The deterministic provider fixture emits a small known PNG as a final `image_generation_call` and emits running/generating/completed lifecycle frames where the transport supports them.

The scenario verifies:

1. selecting `image_generation` places the native tool declaration in the provider request;
2. the live tool card reaches running and completed states without duplicate calls;
3. durable history contains no Base64, data URL, or provider `result` field;
4. the durable result contains one FilePart and one available Exchange attachment;
5. the attachment download returns the expected original image bytes;
6. a later model request contains the image reconstructed from ModelFile;
7. REST history and WebSocket payloads contain metadata references only;
8. retry/resync does not create duplicate durable provider-tool results or file metadata.

### Backend unit and integration coverage

- exhaustive hosted-tool dispatch and explicit unsupported errors;
- OpenAI SDK, ChatGPT OAuth, and LiteLLM request shapes;
- invalid config rejection;
- strict Base64 decoding and pre/post-decode limits;
- corrupt image rejection and media-type detection;
- native artifact sanitization;
- transient output serialization exclusion;
- dual resource preparation, transaction admission, and compensation;
- FilePart and Attachment construction;
- compatible native rehydration;
- cross-adapter FilePart fallback;
- sanitized continuation comparison;
- model without image-input capability receives an explicit placeholder;
- no forced follow-up turn when `end_turn` is not false;
- new migration upgrade behavior and preserved existing builtin settings.

### Frontend coverage

- generated image is visible without expanding diagnostic details;
- preview and download use Exchange URLs;
- running/completed/failed states remain correct;
- unavailable historical attachments disable preview/download;
- payload parsing never accepts Base64 as attachment content.

### Fixture and CI policy

The deterministic fixture is required in normal CI and must fail rather than skip. It uses a committed small image fixture and provider-stream snapshots with no credentials.

Optional live-provider smoke tests may run for OpenAI API and ChatGPT OAuth when credentials and account capability are present. They skip only when prerequisites are absent. Once prerequisites are present, provider rejection, missing attachment, or raw-payload leakage fails the test.

Validation evidence should include:

- focused backend test output;
- OpenAPI/schema diff showing no raw-image field;
- E2E logs for all three runtime paths;
- a downloaded attachment checksum;
- an assertion over serialized durable history and live payloads proving the Base64 fixture substring is absent.

## Alternatives Considered

### Store the provider result directly in the canonical event

Rejected because canonical history would become a blob transport and every history consumer would inherit the payload.

### Add the Exchange URI to model input

Rejected because Attachment lowers to metadata by design and does not provide rich image input.

### Reuse the Exchange file as ModelFile identity

Rejected because Exchange and ModelFile have independent normalization, authorization, and lifecycle contracts.

### Run storage inside an adapter normalizer

Rejected because normalizers are provider-dialect parsers and must not own database/object-storage dependencies.

### Restore provider-specific configuration rules

Rejected because current selectable model options already provide the correct capability boundary. Provider limitations are represented by catalog capability and lowerer support, not Agent-global settings coupling.

## Final Decisions

- One restoration covers OpenAI SDK, ChatGPT OAuth, and LiteLLM.
- Generated image bytes remain transient until stored in Exchange and ModelFile object storage.
- A successful provider-tool result contains both a ModelFile-backed FilePart and an Exchange-backed Attachment.
- The database never stores Base64 or raw image bytes.
- Later model calls rehydrate the ModelFile only in request-local memory.
- Output admission is strict: partial materialization is failure.
- Historical Gemini-specific validation conditions are not part of the restored contract.
