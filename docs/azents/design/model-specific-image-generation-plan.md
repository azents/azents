---
title: "Model-Specific Image Generation Implementation Plan"
created: 2026-07-18
tags: [backend, engine, frontend, llm, storage, tools, security, testenv]
---

# Model-Specific Image Generation Implementation Plan

## Feature summary

Implement the design in
[`model-specific-image-generation.md`](./model-specific-image-generation.md): keep one
model-scoped `image_generation` setting, use provider-hosted execution for OpenAI-family
models, and provide an Azents-executed xAI Imagine function tool for both xAI API-key and
xAI OAuth model options.

The delivery is a stacked PR series. Each phase is reviewable and keeps all selected
built-ins explicit: no advertised capability may be silently omitted or lowered to the
wrong execution path.

## PR stack

### PR 1 — Design and ADR

Branch: `feature/model-specific-image-generation-design`

- Record the effective-capability and model-specific executor decision.
- Define API-key and OAuth behavior, generated-image materialization, errors, security,
  rollout, and validation.

Dependency: current `main`.

### PR 2 — Implementation plan

Branch: `feature/model-specific-image-generation-plan`

- Record phase boundaries, validation matrix, prerequisites, spec impact, and cleanup.

Dependency: PR 1.

### PR 3 — Capability and execution-resolution foundation

Branch: `feature/model-specific-image-generation-runtime`

- Generalize the model capability policy boundary without yet advertising xAI image
  generation.
- Introduce exhaustive model/provider execution resolution.
- Partition provider-hosted tools from client built-in implementations before request
  lowering.
- Ensure OpenAI/ChatGPT behavior is unchanged and direct xAI image-generation resolution
  never reaches the provider-hosted lowerer.
- Keep xAI catalog projection gated until the client implementation lands atomically in
  PR 4.
- Add unit and integration tests for policy and resolution foundations.

Dependency: PR 2.

### PR 4 — xAI Imagine client execution

Branch: `feature/model-specific-image-generation-imagine`

- Atomically project `image_generation` for xAI API-key and xAI OAuth function-calling
  chat models when the client implementation becomes available.
- Add the auto-bound unprefixed `image_generation` client tool.
- Add dependency-injected xAI Imagine HTTP client with bounded request/response handling.
- Reuse xAI API-key credentials and proactively refreshed OAuth credentials.
- Add forced OAuth refresh and one `401` retry.
- Extract reusable generated-image validation and dual materialization.
- Return Exchange attachment and ModelFile-backed file output through the client tool
  result.
- Add deterministic tests for success, auth refresh, errors, cancellation, byte
  validation, storage compensation, and secret redaction.

Dependency: PR 3.

### PR 5 — Validation

Branch: `feature/model-specific-image-generation-validation`

- Add or update deterministic E2E coverage for OpenAI hosted behavior and xAI API-key / OAuth
  client execution.
- Run the planned focused and broad quality checks.
- Record commands, environment, results, fixture evidence, and strict implementation/spec
  comparison.
- Fix implementation defects discovered during validation.

Dependency: PR 4.

### PR 6 — Spec promotion

Branch: `feature/model-specific-image-generation-spec`

- Run spec review against the complete implementation diff.
- Update Agent, model catalog, execution loop, conversation, and file lifecycle specs as
  required.
- Mark the design implemented only after deterministic validation passes.

Dependency: PR 5.

### PR 7 — Cleanup

Branch: `feature/model-specific-image-generation-cleanup`

- Remove this implementation plan after specs and code become authoritative.
- Keep the adopted ADR and implemented design as historical rationale.

Dependency: PR 6.

## Runtime changes by phase

### Capability foundation

- Rename or replace `supported_provider_hosted_tools()` with an effective built-in
  capability policy.
- Preserve trusted explicit source metadata and existing OpenAI support behavior.
- Add xAI API-key and OAuth policy based on chat mode and function-calling support.
- Add a closed execution-strategy type and exhaustive resolver.
- Carry selected integration identity needed by client implementation construction and
  forced OAuth refresh.
- Keep `RunRequest` provider-hosted fields limited to provider-hosted specifications.

### Imagine execution

- Create an internal auto-bound toolkit rather than a user-configured toolkit record.
- Build the client only for resolved xAI image generation.
- Use `grok-imagine-image`, one output, `1k`, `auto`, and `b64_json` defaults.
- Do not add provider/model selection parameters to the model-visible tool input.
- Share existing generated-image storage policy instead of duplicating Base64 or file
  lifecycle behavior.

### Presentation

- Reuse current attachment and file output contracts.
- Preserve provider-tool presentation for OpenAI.
- Render xAI client tool attachment through existing client tool card behavior.
- Avoid public API or generated-client changes unless validation discovers a missing
  attachment projection contract.

## Test strategy by phase

### PR 3 tests

- xAI API-key and OAuth function-calling chat entries advertise `image_generation`.
- Non-function-calling and non-chat xAI entries do not advertise it.
- New Grok identifiers receive support without an identifier allowlist.
- OpenAI and ChatGPT resolve `image_generation` as provider-hosted.
- xAI API-key and OAuth resolve it as client-executed.
- Selected unsupported and unknown capabilities fail explicitly.
- Lowerers receive only provider-hosted tools.

### PR 4 tests

- API-key Authorization uses the selected integration key.
- OAuth Authorization uses the refreshed access token.
- OAuth first `401` forces refresh and retries exactly once.
- OAuth second `401`, `403`, `429`, timeout, retryable `5xx`, malformed JSON, missing Base64,
  invalid media, oversized content, and cancellation are classified correctly.
- Secrets are absent from exceptions, events, logs, and file metadata.
- Successful generation creates one Exchange attachment and one ModelFile file part.
- Partial materialization is compensated and retry admission remains idempotent.

### PR 5 E2E primary matrix

| Model option | Flag | Expected execution | Expected result |
| --- | --- | --- | --- |
| OpenAI | enabled | provider-hosted | provider result attachment |
| OpenAI | disabled | no image tool | no generation activity |
| xAI API key | enabled | client Imagine | client result attachment and file part |
| xAI OAuth | enabled | client Imagine | client result attachment and file part |
| xAI OAuth | enabled, first `401` | refresh + one retry | successful attachment |
| xAI OAuth | enabled, repeated `401` | client failure | sanitized reconnect error |
| xAI | disabled | no client tool | no generation activity |

## Fixture and prerequisite support

Deterministic CI must not require live xAI credentials, spend, quota, or subscription
entitlement.

Required fixture support:

- deterministic xAI model capable of calling `image_generation`;
- injected Imagine HTTP mock transport;
- OAuth refresh mock capable of returning a replacement token;
- generated raster fixture small enough for normal storage and preview paths;
- invalid and oversized fixtures for admission failures.

Optional live validation may use retained xAI API-key and OAuth test credentials. Token
values must never be printed or attached. Missing live credentials skip only optional live
tests. Any deterministic fixture failure fails CI.

## Quality checks

Run from `python/apps/azents` unless otherwise noted:

- focused Ruff checks for changed Python files;
- focused Pyright checks for changed Python files;
- focused Pytest suites for catalog, run resolution, lowerers, OAuth, tool execution,
  generated image materialization, and event projection;
- complete relevant package tests when focused checks pass;
- deterministic E2E tests from `testenv/azents/e2e` when fixture behavior is added;
- frontend format, lint, typecheck, and focused tests only if frontend code changes.

No check may be bypassed with `--no-verify` or equivalent.

## Spec impact candidates

- `docs/azents/spec/domain/agent.md`
- `docs/azents/spec/domain/model-catalog.md`
- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/file-exchange-storage.md`
- `docs/azents/spec/flow/xai-oauth.md`, if one exists or is introduced by concurrent work

Spec promotion must distinguish effective capability from execution ownership and preserve
existing provider/client event semantics.

## Rollout and observability

- Capability and resolver ship together before the Imagine client becomes selectable.
- Imagine client execution is enabled simultaneously for xAI API key and OAuth.
- Record provider, credential mode, status class, latency, response size, and retry count as
  structured fields without prompt or credential values.
- Track OAuth refresh, permission, entitlement, rate-limit, provider-unavailable, invalid
  media, and materialization failures separately.
- Existing OpenAI image generation remains the regression baseline.

## Blockers and external actions

No external action blocks deterministic implementation or CI.

Optional live OAuth validation depends on an entitled xAI OAuth account. A missing or
denied entitlement does not block the release because the public product behavior is
covered deterministically and runtime `403` handling is explicit.

## Cleanup

After implementation, validation, and spec promotion:

- delete this plan in the cleanup PR;
- retain the adopted ADR;
- retain the implemented design document;
- keep current behavior in living specs and code.
