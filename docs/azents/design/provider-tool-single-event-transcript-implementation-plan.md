---
title: "Provider Tool Single-Event Transcript Implementation Plan"
created: 2026-07-19
updated: 2026-07-19
tags: [backend, engine, frontend, llm, tools, storage, testing]
---

# Provider Tool Single-Event Transcript Implementation Plan

## Feature Summary

Implement [ADR-0168](../adr/0168-use-single-provider-tool-events.md) and the [Provider Tool Single-Event Transcript Design](./provider-tool-single-event-transcript.md).

The final system stores every provider-hosted native item as one `provider_tool_call`, uses ToolOutput parts as the canonical tool file-delivery contract, lowers same-native generated images plus Exchange URI context without duplication, and renders one provider tool card.

## Stack

Stack prefix: `Provider tool single-event transcript`

| PR | Branch | Base | Scope |
| --- | --- | --- | --- |
| 1/8 | `design/provider-tool-call-output-contract` | `main` | ADR-0168 and approved feature design |
| 2/8 | `plan/provider-tool-single-event-transcript` | PR 1 branch | This phased implementation plan |
| 3/8 | `feature/provider-tool-single-event-production` | PR 2 branch | Produce single provider call events and canonical generated-file output parts while retaining transitional read types |
| 4/8 | `feature/provider-tool-single-event-backend-cutover` | PR 3 branch | Follow-up migration, remove provider result contract, multi-item lowering, and backend consumer cutover |
| 5/8 | `feature/provider-tool-single-event-frontend` | PR 4 branch | OpenAPI/client regeneration and one-card frontend projection |
| 6/8 | `test/provider-tool-single-event-validation` | PR 5 branch | Deterministic E2E validation, complete quality matrix, and discovered fixes |
| 7/8 | `docs/provider-tool-single-event-spec` | PR 6 branch | Spec promotion and design implementation marker |
| 8/8 | `chore/provider-tool-single-event-cleanup` | PR 7 branch | Remove this temporary implementation plan |

All PRs request review from `hardtack`. Create the complete stack before monitoring CI. Do not merge without explicit user approval.

## Phase Dependencies

```mermaid
flowchart LR
    D[1 Design] --> P[2 Plan]
    P --> N[3 Single-event production]
    N --> B[4 Backend cutover]
    B --> F[5 API and frontend]
    F --> V[6 Validation]
    V --> S[7 Spec promotion]
    S --> C[8 Cleanup]
```

PR 3 intentionally keeps the existing provider-result read contract so its producer cutover can remain independently deployable and testable. PR 4 performs the clean migration and removes transitional types. No legacy runtime parser remains after PR 4.

## PR 3: Single-Event Production

### Runtime changes

- Classify Responses `image_generation_call` as `provider_tool_call`.
- Materialize provider generated files onto `ProviderToolCallPayload.semantic.output`.
- Store generated image output as one FileOutputPart plus one AttachmentOutputPart.
- Store client-generated image delivery as FileOutputPart plus AttachmentOutputPart in `ClientToolResultPayload.output`.
- Keep existing result and attachments fields readable during this phase only so the branch remains compatible with pre-migration rows.
- Keep Base64, bytes, data URLs, credentials, and raw provider bodies transient and excluded.

### Tests

- Registry classification and normalization tests.
- Provider and client generated-file admission tests.
- Atomic dual-resource persistence and compensation tests.
- Event JSON assertions proving one provider call event and blob-free output parts.

## PR 4: Backend Cutover

### Data and schema

- Generate a new Alembic revision after `25bc37eadace`; never modify the executed migration.
- Convert provider result rows to provider call rows.
- Convert provider/client tool attachments to AttachmentOutputPart values.
- Remove tool payload attachments keys.
- Replace the PostgreSQL `event_kind` enum without `provider_tool_result`.
- Update `db-schemas/rdb/revision`.

### Event contract

- Remove `EventKind.PROVIDER_TOOL_RESULT` and `ProviderToolResultPayload`.
- Remove tool-level attachments fields from provider calls and client results.
- Use one provider lifecycle status vocabulary covering live and terminal states.
- Update payload validation, serialization, transcript repositories, message projection, context accounting, compaction, continuity, fork context, availability filters, model-file references, emit, and live projections.

### Lowering

- Change Responses event lowering to return zero-to-many native input items.
- Rehydrate compatible provider image calls from FileOutputPart on the same event.
- Treat native-covered semantic input and references as consumed.
- Lower AttachmentOutputPart as a bounded user-compatible Exchange URI context item.
- Exclude consumed FileOutputPart from generic lowering.
- Preserve rich-file plus attachment context fallback across incompatible adapters.
- Update every supported lowerer and its tests.

### Tests

- Migration upgrade/downgrade and enum replacement tests.
- Closed event union and payload validation tests.
- Same-native replay, cross-native replay, missing ModelFile, unavailable attachment, and deduplication tests.
- Compaction, context estimate, emit, message projection, fork context, and availability tests.
- Full backend Ruff, Pyright, and Pytest.

## PR 5: API and Frontend

### API and generated clients

- Regenerate public OpenAPI after the event union change.
- Regenerate Python and TypeScript public clients through the OpenAPI generation workflow.
- Do not edit generated files manually.

### Frontend

- Remove provider result event types and reducer cases.
- Remove `applyProviderToolCallOutput` and result-to-call merge state.
- Project OutputTextPart and AttachmentOutputPart from provider call semantic output.
- Keep FileOutputPart model-only.
- Replace live running calls with durable completed calls by semantic call ID.
- Render one image-generation card with one downloadable attachment.
- Preserve existing layout outside provider tool event projection.
- Add or update Storybook stories for running, completed image, failed, and generic attachment states.

### Tests

- Projection reducer tests for live-to-durable replacement, history reload, and resync.
- Attachment deduplication and FileOutputPart-hidden tests.
- TypeScript format, lint, typecheck, and build.

## PR 6: Validation

### Deterministic E2E matrix

| Scenario | Durable history | Next request | UI/result expectation |
| --- | --- | --- | --- |
| Provider image generation | One completed provider_tool_call with FileOutputPart + AttachmentOutputPart | Same-native native image result plus one Exchange URI context | One provider card, one attachment |
| Same-native continuation | No raw bytes in event/native artifact | FileOutputPart consumed once | No duplicated rich image |
| Cross-native continuation | Same canonical event | Rich image fallback plus Exchange URI metadata | Model retains image and URI knowledge |
| Compaction | Semantic output and bounded attachment metadata included | Native artifact excluded from summary | Continuation retains URI fact |
| Missing ModelFile | Durable attachment remains independently available | Explicit unavailable-image placeholder plus attachment context | Download remains available when Exchange exists |
| Expired Exchange file | ModelFile lifecycle remains independent | Attachment availability metadata reflects expiration | UI shows normal unavailable history state |
| xAI client image | Client result output contains FileOutputPart + AttachmentOutputPart | Normal client tool result lowering | One downloadable attachment |
| History/live resync | One provider event | N/A | One stable card before and after refresh |

### Fixture and prerequisites

- Reuse the deterministic OpenAI-compatible image-generation fixture and request-capture proxy.
- Extend fixtures with bounded synthetic image bytes and semantic Exchange URI assertions.
- Add an xAI client-executor fixture path if the existing unit fixture cannot exercise complete event projection.
- No external credential is required for blocking CI.
- Live OpenAI/xAI runs are optional diagnostics and skip when credentials or entitlement are absent.
- Never store full provider-sized payloads, secrets, or unbounded Base64 in fixtures or evidence.

### Evidence

- Backend Ruff, format, Pyright, targeted and full Pytest.
- Migration tests.
- OpenAPI/client generation checks.
- TypeScript format, lint, typecheck, and build.
- Deterministic E2E request capture and frontend projection assertions.
- Strict implementation-to-spec comparison table in the validation PR.

Discovered behavior defects are fixed in PR 6 unless they require rewriting an earlier contract. If an earlier branch changes, rebase the stack with `scripts/rebase-stacked-prs.sh`.

## PR 7: Spec Promotion

Run `/spec-review` and update current behavior in:

- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/file-exchange-storage.md`
- `docs/azents/spec/flow/context-compaction.md`
- `docs/azents/spec/flow/session-context-inspector.md`
- `docs/azents/spec/flow/chat-session-resync.md`

Set `implemented: 2026-07-19` on the feature design only after validation is complete. ADR-0168 remains immutable.

## PR 8: Cleanup

Delete this implementation plan after implementation and specs are current. Keep ADR-0168, the implemented feature design, living specs, and code as the durable sources of truth.

## Rollout and Recovery

- Deliver migration and runtime cutover atomically in the backend phase.
- No feature flag, dual-write period, or final legacy parser.
- Preserve the preceding deployable artifact for rollback.
- Migration downgrade restores provider result rows, tool attachments fields, and the previous event enum for code rollback.
- Do not merge any stack PR without explicit user approval.

## Blockers

None identified. The existing provider image proxy, deterministic E2E substrate, Exchange storage, ModelFile materializer, and provider semantic registry cover the required implementation boundaries.
