---
title: "Provider Tool Semantic Transcript Implementation Plan"
created: 2026-07-18
updated: 2026-07-18
tags: [backend, engine, llm, tools, compaction, testing]
---

# Provider Tool Semantic Transcript Implementation Plan

## Feature Summary

Implement the provider-neutral semantic transcript contract defined by:

- `docs/azents/design/provider-tool-semantic-transcript.md`
- `docs/azents/adr/0167-normalize-provider-tool-semantic-transcript.md`

The implementation promotes provider-exposed hosted-tool input, output, references, and attachments into canonical events so compaction and cross-native lowering do not depend on opaque native artifacts or per-tool branches.

## Stack

### PR 1 — Design

Branch: `feature/provider-tool-semantic-transcript-design`

- Record the canonical adapter-boundary decision in ADR-0167.
- Define semantic content, migration, security, and test policy.

### PR 2 — Implementation plan

Branch: `feature/provider-tool-semantic-transcript-plan`

- Record phase boundaries, validation matrix, prerequisites, and spec impact.

### PR 3 — Canonical contract and adapter normalization

Branch: `feature/provider-tool-semantic-transcript-normalization`

Depends on PR 2.

- Add `ProviderToolSemanticContent` and `ProviderToolReference` canonical models.
- Replace provider-tool call arguments and result output fields with the shared semantic contract.
- Add a generated Alembic migration that rewrites existing provider-tool event payload JSON.
- Add registry-based Responses hosted-tool item normalization.
- Normalize Web search, file search, code interpreter, image generation, and generic MCP-shaped output where exposed.
- Preserve provider-generated image materialization through semantic output and attachments.
- Add canonical schema, migration, output-normalizer, and registry contract tests.

### PR 4 — Generic consumers and validation

Branch: `feature/provider-tool-semantic-transcript-consumers`

Depends on PR 3.

- Add one shared provider-tool semantic renderer.
- Use it for cross-native lowering, compaction summary input, continuity rendering, and token estimation.
- Extend deterministic E2E/provider fixture coverage to capture pre/post-compaction model requests.
- Run targeted and full backend quality checks.
- Fix implementation drift found during validation.

### PR 5 — Spec promotion and cleanup

Branch: `feature/provider-tool-semantic-transcript-spec`

Depends on PR 4.

- Run spec review.
- Update current context-compaction, execution-loop, and conversation specs.
- Mark the design implemented after verification.
- Remove this temporary implementation plan.

## Dependencies

- PRs are stacked and must merge front to back.
- PR 3 changes the persistent event JSON contract and must include its migration in the same atomic phase.
- PR 4 assumes all provider-tool payloads use the new semantic contract.
- PR 5 begins only after deterministic request-capture validation passes.

## Runtime and Data Changes

### Canonical event payload

Both provider-tool event payloads receive required nested semantic content and attachments. Existing legacy call `arguments` and result `output` fields are removed.

### Database migration

Generate a new Alembic revision from the current backend migration head. The migration updates JSONB payloads for `provider_tool_call` and `provider_tool_result`, preserving existing canonical information without parsing native artifacts.

No runtime dual-read or legacy payload fallback is added.

### Adapter normalization

Use a single registry for recognized Responses provider-tool output item types. Each entry must include semantic extraction. Typed lifecycle-only events remain live projections and do not become incomplete durable events.

### Model input

Same-native compatible artifacts retain priority. Incompatible targets and compaction use the shared semantic renderer.

## Validation Matrix

| Behavior | Unit | Integration | Deterministic E2E |
| --- | --- | --- | --- |
| Canonical input/output/reference schema | Required | Migration parse | Indirect |
| Web-search action/query/source preservation | Required | Normalizer completion | Required |
| File-search result/reference preservation | Required | Normalizer completion | Optional |
| Code-interpreter code/log preservation | Required | Normalizer completion | Optional |
| Generated image file preservation | Required | Provider output admission | Existing coverage plus regression |
| Same-native replay | Required | Lowerer request | Required |
| Cross-native semantic fallback | Required | Lowerer request | Required |
| Compaction input preservation | Required | Manual/auto compaction | Required |
| Token estimation parity | Required | Auto-compaction trigger | Indirect |
| Reference and output bounds | Required | Oversized fixture | Optional |
| Legacy payload migration | Migration test | Repository load | Not applicable |

## E2E Plan

Primary deterministic scenario:

1. Configure an Agent fixture with hosted Web search enabled.
2. Emit a provider Web-search output item containing a search action, query, and source URLs.
3. Emit a separate assistant answer.
4. Verify durable context inspection exposes normalized semantic input and references.
5. Force compaction through a small effective context window.
6. Continue through an incompatible model fixture so native artifact replay is unavailable.
7. Capture the next model request and verify it contains the canonical query/source rendering and assistant answer, but no raw native artifact JSON.

A live provider test is optional and diagnostic only. It is skipped when credentials, model capability, or provider availability are absent. Deterministic fixture failure blocks shipping.

## Fixture and Prerequisite Support

- Extend the existing deterministic Responses model/provider fixture rather than introducing external Web-search dependencies.
- Add request capture for the model call after compaction.
- Seed a small-context Agent model option to trigger compaction deterministically.
- No OAuth token or external provider credential is required for blocking validation.
- Existing generated-image fixtures remain the prerequisite for FilePart regression coverage.

## Quality Checks

From `python/apps/azents`:

```console
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Run focused suites during implementation:

```console
uv run pytest src/azents/engine/events/types_test.py
uv run pytest src/azents/engine/events/responses_output_test.py
uv run pytest src/azents/engine/events/openai_responses_test.py
uv run pytest src/azents/engine/events/litellm_responses_test.py
uv run pytest src/azents/engine/events/engine_adapter_test.py
uv run pytest src/azents/engine/events/filters_test.py
uv run pytest src/azents/engine/events/provider_output_test.py
```

Run the relevant migration upgrade test and deterministic E2E scenario before spec promotion.

## Blockers and Manual Actions

No known implementation blocker.

Potential provider schema differences are handled through explicit adapter extractors and unit fixtures. Live provider availability does not block the deterministic validation path.

## Spec Impact Candidates

- `docs/azents/spec/flow/context-compaction.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/flow/file-exchange-storage.md` if provider file semantics change

## Rollout and Cleanup

- Apply migration and runtime change atomically.
- Do not keep dual canonical payload contracts.
- After PR 4 validation, promote current behavior into specs and mark the design implemented.
- Delete this plan in PR 5 after specs become the current source of truth.
