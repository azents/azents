---
title: "Provider-Hosted Image Generation Implementation Plan"
created: 2026-07-17
updated: 2026-07-17
tags: [backend, engine, frontend, llm, storage, tools, testenv]
---

# Provider-Hosted Image Generation Implementation Plan

## Feature Summary

Restore the semantic provider-hosted `image_generation` builtin across OpenAI SDK, ChatGPT OAuth, and LiteLLM. Generated image bytes remain transient until Azents stores the original as an Exchange attachment and a normalized copy as a ModelFile. Durable provider-tool results reference both resources without persisting Base64 or raw bytes.

Design: [`provider-hosted-image-generation.md`](./provider-hosted-image-generation.md)

Decision: [`ADR-0164`](../adr/0164-materialize-provider-generated-images-as-file-resources.md)

## Stack

### PR 1 — Design

- Add the feature design and ADR.
- Record dual-resource materialization, request-local rehydration, validation policy, and cross-lowerer requirements.

### PR 2 — Implementation plan

- Define phased delivery and validation requirements.
- Record fixture, migration, spec, and cleanup boundaries.

### PR 3 — Runtime capability and request lowering

- Restore `image_generation` in the implemented builtin registry.
- Add trusted capability projection for supported OpenAI, ChatGPT OAuth, and LiteLLM-routed models.
- Add a new forward Alembic migration for stored capability snapshots while preserving existing builtin settings.
- Replace silent hosted-tool skipping with exhaustive dispatch.
- Lower `image_generation` through OpenAI SDK, ChatGPT OAuth, and LiteLLM.
- Add focused registry, catalog, validation, migration, and lowerer tests.

Dependency: PR 2.

### PR 4 — Generated image materialization

- Add the provider-neutral transient generated-file output contract.
- Decode and validate provider image results without serializing bytes.
- Prepare Exchange original, optional preview, and normalized ModelFile resources.
- Admit both resource metadata records and the provider-tool result in the successful model-output transaction.
- Add compensation and strict partial-failure behavior.
- Replace unavailable generated-image placeholders with FilePart and Attachment references.
- Add focused normalizer, storage, event admission, and failure tests.

Dependency: PR 3.

### PR 5 — Model replay and user presentation

- Rehydrate compatible `image_generation_call.result` from ModelFile only in request-local memory.
- Sanitize continuation comparison so request-local Base64 does not break stored-response continuation.
- Add cross-adapter FilePart rich-image fallback and explicit unsupported placeholders.
- Render generated image attachments directly in the provider-tool card.
- Add OpenAI SDK, ChatGPT OAuth `store=false`, LiteLLM, continuation, frontend projection, and component tests.

Dependency: PR 4.

### PR 6 — Validation

- Add deterministic provider fixtures and E2E coverage for all three runtime paths.
- Verify live lifecycle, durable output, attachment download, later model reuse, retry/resync behavior, and absence of Base64 from durable/live payloads.
- Run focused backend and frontend quality suites.
- Record environment, commands, fixture snapshots, checksums, and implementation/spec comparison.
- Fix validation findings in this PR or the responsible earlier phase, then rebase following branches.

Dependency: PR 5.

### PR 7 — Spec promotion

- Run spec review.
- Update Agent, model catalog, conversation, execution-loop, and file-exchange specs.
- Mark the design implemented only after validation passes.
- Keep ADR-0164 unchanged after acceptance.

Dependency: PR 6.

### PR 8 — Cleanup

- Remove this implementation plan.
- Remove obsolete image-generation migration notes or placeholder-specific references found during validation.
- Do not include runtime behavior changes.

Dependency: PR 7.

## Runtime and Data Changes

- `BuiltinToolSpec` remains the semantic Engine input.
- `NormalizedAdapterOutput` gains a serialization-excluded transient generated-file collection.
- `ProviderToolResultPayload` continues to use existing `output` and `attachments` fields.
- `FileOutputPart` references ModelFile metadata only.
- `Attachment` references Exchange metadata only.
- No public schema carries raw bytes or Base64.
- A new migration updates capability snapshots only; existing model-option builtin settings remain unchanged.

## Test Strategy by Phase

| Phase | Required validation |
| --- | --- |
| Runtime capability | Registry, model-option validation, catalog projection, migration upgrade, OpenAI/ChatGPT/LiteLLM request shapes, explicit unsupported errors |
| Materialization | Strict Base64 and image validation, size limits, native artifact sanitization, transient serialization exclusion, dual resource admission, compensation, no partial result |
| Replay and UI | Compatible native rehydration, `store=false` replay, sanitized continuation, cross-adapter image fallback, unsupported placeholder, direct generated-image rendering |
| Validation | Deterministic E2E matrix, attachment checksum, later model request image assertion, history/live Base64 absence, retry/resync deduplication |

## E2E Primary Validation Matrix

| Runtime path | Declaration | Live lifecycle | Durable FilePart | Exchange Attachment | Later model reuse | No raw payload |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI SDK | required | required | required | required | required | required |
| ChatGPT OAuth | required | required | required | required | required with `store=false` | required |
| LiteLLM | required | required | required | required | required | required |

## Fixtures and Prerequisites

- Commit a small deterministic image fixture and its SHA-256 checksum.
- Extend the fake Responses stream fixture to emit image generation progress and a completed result.
- Capture the second provider request so tests can assert request-local image rehydration.
- Keep deterministic tests credential-free and mandatory in normal CI.
- Optional live smoke tests require provider credentials and an account/model with image-generation capability. Missing prerequisites skip; configured prerequisites turn provider rejection or output leakage into failure.

## Known Risks and Mitigations

- **Object upload before DB admission**: use preallocated keys, compensation deletion, and object-store lifecycle cleanup for the crash window.
- **Large provider payload**: reject by encoded and decoded bounds before persistence.
- **Continuation mismatch**: compare sanitized items while preserving full request-local input for non-continuation calls.
- **Stale model snapshots**: migrate stored capability snapshots and retain runtime lowerer validation.
- **Provider feature drift**: use explicit capability sources or curated overrides rather than generic output modalities.
- **Duplicate output after retry/resync**: use run/call/output identity and deterministic event external identity in admission tests.

## Spec Impact Candidates

- `docs/azents/spec/domain/agent.md`
- `docs/azents/spec/domain/model-catalog.md`
- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/file-exchange-storage.md`
- `docs/azents/spec/flow/chat-session-resync.md` if validation changes projection behavior

## Rollout and Cleanup

- Existing model-option builtin lists do not gain `image_generation` automatically.
- New or newly normalized options use the current defaulting rule for supported implemented builtins.
- Unsupported or stale selections fail explicitly before provider dispatch.
- After validation and spec promotion, delete this plan in the cleanup PR.
