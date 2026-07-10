---
title: "xAI API Key Provider Implementation Plan"
created: 2026-07-10
updated: 2026-07-10
tags: [backend, frontend, engine, api, testenv, documentation, process]
---

# xAI API Key Provider Implementation Plan

## Feature Summary

Implement the stable `xai` API-key provider defined in [xAI API Key Provider](xai-api-key-provider.md). The provider remains separate from `xai_oauth`, reuses encrypted API-key CRUD, shares the provider-neutral xAI Responses transport, and uses a separate system catalog projected from LiteLLM's `xai` family.

## Stack and Phase Boundaries

| PR | Phase | Scope | Depends on |
|---:|---|---|---|
| 1/7 | Design | Final feature contract and validation policy | none |
| 2/7 | Implementation plan | This stack plan, validation matrix, prerequisites, spec candidates | design |
| 3/7 | Backend/API/runtime/catalog | Provider enum and migration, encrypted credential mapping, capability API, provider-neutral xAI endpoint, runtime/lowerer/catalog support, OpenAPI and generated clients, Python tests | plan |
| 4/7 | Frontend UX | API-key provider selection, labels, setup guidance, localization, pure UI stories/tests | backend generated clients |
| 5/7 | E2E validation | Deterministic public API scenario, targeted quality gates, validation report, implementation-versus-spec comparison | frontend |
| 6/7 | Spec promotion | Living specs, design implementation marker, final ADR assessment | validation |
| 7/7 | Cleanup | Remove this stale implementation plan and its generated index count | spec promotion |

## Phase 1: Backend, API, Runtime, Catalog, and Clients

### Data and API

- Add `LLMProvider.XAI = "xai"`.
- Generate a new Alembic revision that adds `xai` to PostgreSQL `llm_provider`; update the schema revision pointer.
- Map `xai` to `ApiKeySecrets` and no plaintext config.
- Expose `xai` from the provider capability endpoint as non-experimental.
- Regenerate public OpenAPI and Python/TypeScript clients from the schema; never edit generated files manually.

### Runtime and catalog

- Move `https://api.x.ai/v1` to a provider-neutral xAI API constant used by API-key and OAuth credentials.
- Map `xai` to `xai/` runtime models and explicit LiteLLM xAI transport kwargs.
- Apply the existing xAI instruction placement, hosted web search, and prompt-cache policies to both credential modes through provider-capability sets or predicates.
- Add a separate `xai` system catalog projected from the LiteLLM `xai` family, with xAI developer mapping and provider-facing prefix removal.
- Keep OAuth refresh restricted to `xai_oauth`.

### Tests

- Provider enum, secret/config validation, repository encryption, and capability response.
- Migration/schema checks.
- Runtime model and credential kwargs.
- xAI instruction and hosted-tool lowering for API key and OAuth.
- System catalog projection and admin provider support.
- Generated OpenAPI/client checks.

## Phase 2: Frontend UX

- Add `xai` to the backend-authorized provider option list and display maps.
- Label it `xAI API key`; keep `xAI Grok OAuth` separate and experimental.
- Reuse `ApiKeyForm`; omission of `secrets` on edit preserves the key.
- Add provider-specific setup copy that distinguishes xAI developer API billing from SuperGrok/X Premium.
- Add EN, FR, JA, and KO translations.
- Add or extend pure UI stories for API-key and OAuth create states.

### Tests

- Story/component assertions for both xAI options and secret-safe edit behavior.
- TypeScript format, lint, typecheck, and build.

## Phase 3: E2E and Validation

### Deterministic E2E

Add a public API scenario using a fake key:

1. Provider capabilities include stable `xai` and experimental `xai_oauth`.
2. A permitted workspace member creates an `xai` integration.
3. The response and subsequent list/get omit the key.
4. Alias/enabled updates omit `secrets` and preserve the stored credential.
5. Delete succeeds.
6. Existing permission tests continue to reject a member without `LLM_INTEGRATIONS_WRITE`.

The deterministic scenario must not call xAI. Runtime request behavior remains covered by mocked backend adapter tests.

### Validation report

Record:

- commands and environment;
- targeted and full applicable quality-gate results;
- E2E evidence;
- generated-client consistency;
- migration ordering check;
- strict implementation-versus-design/spec comparison;
- discovered failures and fixes.

## E2E Primary Validation Matrix

| Behavior | Primary verification | CI policy | Evidence |
|---|---|---|---|
| Provider discovery and separation | Public API E2E | required | provider values, credential types, experimental flags |
| Encrypted API-key CRUD and redaction | Public API E2E + repository test | required | response fields and encrypted repository round trip |
| Edit without secret replacement | Public API E2E/backend test | required | update request omits secrets; integration remains usable in mapping test |
| System catalog projection | Backend integration/unit tests | required | provider-facing and runtime identifiers |
| Responses instruction/tool routing | Mocked adapter tests | required | captured request kwargs/input/tools |
| Frontend provider distinction | Story/component test | required | xAI API-key and OAuth create states |
| Current-model live call | Optional live external smoke | not required in deterministic CI | redacted model/status record |

## Fixture and Prerequisite Requirements

### Deterministic CI

No external credential or provider fixture is required. Use fake API keys and mocked transport. Existing workspace/user/integration fixtures are sufficient; extend the public provider integration E2E scenario rather than seeding rows directly.

### Optional live verification

A live smoke test requires `XAI_API_KEY` and a current model identifier. If implemented, the testenv prerequisite contract records only present/missing status and safe model metadata. It must never store or print the key, bearer header, raw request, or raw provider response body.

Skip/fail rules:

- scheduled optional run without a key: skip with prerequisite guidance;
- maintainer-requested live verification without a key: fail;
- deterministic CI: never attempts the live call.

## Blockers and Manual Actions

- No implementation blocker.
- Deployment must apply the PostgreSQL enum migration before application code accepts `provider=xai` writes.
- After deployment, an operator refreshes the xAI system catalog before users select models.
- Live smoke verification is optional and blocked without an operator-supplied key; it does not block shipping.

## Spec Impact Candidates

- `docs/azents/spec/flow/xai-oauth.md`: clarify coexistence and shared provider-neutral inference endpoint.
- New `docs/azents/spec/flow/xai-api-key.md`: provider identity, CRUD, runtime, catalog, UX, security, rollout.
- `docs/azents/spec/domain/model-catalog.md`: add the `xai` system catalog and shared source-family behavior.
- `docs/azents/spec/domain/agent.md`: add the API-key provider to integration models if the provider list is enumerated.
- `docs/azents/spec/flow/agent-execution-loop.md`: update only if xAI transport capability rules are enumerated there.

No ADR is planned unless implementation introduces a new persistent contract beyond the approved design.

## Rollout

1. Merge and deploy from the front of the stack.
2. Apply database migration before enabling new application code.
3. Refresh the `xai` system catalog.
4. Verify provider discovery, integration creation, and a current-model run.
5. Keep `xai_oauth` independent throughout rollout and rollback.

## Cleanup

After validation and spec promotion, delete this plan in PR 7/7. The design, living specs, migration, code, tests, generated schemas, and validation report remain as the durable record.
