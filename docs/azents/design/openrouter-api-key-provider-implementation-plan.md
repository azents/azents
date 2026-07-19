---
title: "OpenRouter API Key Provider Implementation Plan"
created: 2026-07-19
updated: 2026-07-19
tags: [backend, frontend, engine, security, api, testenv, process]
---

# OpenRouter API Key Provider Implementation Plan

## Feature Summary

Implement the approved OpenRouter API-key provider design as an eight-PR stack. OpenRouter becomes an integration-scoped provider whose authenticated account catalog exposes all usable text-output models without an Azents allowlist or LiteLLM metadata visibility gate. Runtime execution reuses LiteLLM Responses with OpenRouter-specific wire semantics and delegates routing and data-policy control to OpenRouter account settings.

Design sources:

- [OpenRouter API Key Provider](./openrouter-api-key-provider.md)
- [ADR-0169: Add OpenRouter as an Integration-Scoped LLM Provider](../adr/0169-add-openrouter-as-an-integration-scoped-llm-provider.md)

## Delivery Constraints

- Keep every PR reviewable and stacked on the previous phase.
- Create the complete PR stack before monitoring CI.
- Do not merge any PR without explicit user approval.
- Do not push directly to `main`.
- Do not edit generated API clients manually; regenerate from the dumped OpenAPI specifications.
- Generate the PostgreSQL enum migration with Alembic and update the revision pointer.
- Preserve the fixed OpenRouter API origin; do not add user-controlled base URLs.
- Preserve existing integration catalog synchronization, failure, and retry semantics.
- Required verification is credential-free. Live OpenRouter verification is optional and separately gated.
- Product behavior verification belongs in E2E; tests do not write directly to the product database.

## PR Stack

### PR 1/8 — Design

Branch: `feature/openrouter-provider-01-design`

Contents:

- ADR-0169 with accepted product and architecture decisions in Draft state.
- OpenRouter provider design, capability policy, security boundary, and test strategy.

Validation:

- Documentation frontmatter and generated index validation through pre-commit.
- No runtime behavior changes.

### PR 2/8 — Implementation Plan

Branch: `feature/openrouter-provider-02-plan`

Contents:

- This multi-phase implementation and validation plan.
- Explicit PR dependencies, E2E matrix, fixture needs, spec candidates, rollout, and cleanup criteria.

Validation:

- Documentation frontmatter and generated index validation through pre-commit.
- No runtime behavior changes.

### PR 3/8 — Phase 1: Provider and Account Catalog

Branch: `feature/openrouter-provider-03-catalog`

Depends on PR 2.

Data and API scope:

- Add `LLMProvider.OPENROUTER` and `LLMModelDeveloper.OTHER`.
- Generate the additive PostgreSQL `llm_provider` enum migration and update the revision pointer.
- Reuse `ApiKeySecrets` with no provider config.
- Add OpenRouter to the public provider capability endpoint as stable `api_key`.
- Add OpenRouter to integration-scoped catalog providers.
- Implement authenticated `/models/user?output_modalities=text` listing with fixed endpoint, bounded source metadata, skip diagnostics, and existing retry-block policy.
- Implement direct OpenRouter projection without a LiteLLM metadata match requirement.
- Preserve exact provider model ids and construct `openrouter/<id>` runtime ids.
- Add neutral publisher mapping and remove the unknown-to-Anthropic fallback.
- Project conservative context, text/image input, function tools, reasoning, parameters, and semantic web-search capabilities.
- Regenerate public OpenAPI and generated Python and TypeScript public clients so the phase is contract-complete.

Tests:

- Enum and credential mapping tests.
- Provider capability API tests.
- Listing response, malformed response, status classification, publisher, metadata-bounding, and capability tests.
- Direct projection and no-LiteLLM-match visibility tests.
- Integration creation/catalog lifecycle service tests.
- Migration upgrade/downgrade SQL verification.
- Generated-client tests and consistency checks.

### PR 4/8 — Phase 2: Responses Runtime

Branch: `feature/openrouter-provider-04-runtime`

Depends on PR 3.

Runtime scope:

- Add `openrouter/` LiteLLM model mapping.
- Build fixed API base, `custom_llm_provider=openrouter`, API key, and `X-OpenRouter-Title` credential kwargs.
- Keep OpenRouter on `LiteLLMResponsesLowerer` and `LiteLLMResponsesModelAdapter`.
- Add provider-first hosted-tool target and standard Responses `web_search` lowering.
- Disable Anthropic cache-control for all OpenRouter models.
- Preserve normal Responses instructions and stateless full-transcript behavior.
- Reuse common usage/cost extraction and `ModelProviderFailure` classification.

Tests:

- Runtime model and credential mapping tests.
- Engine adapter selection and request kwargs tests.
- Text stream, function tool, reasoning, web search, and usage normalization tests.
- Unknown-publisher and Claude-through-OpenRouter cache-control regression tests.
- 401/402/403/404/429/5xx provider failure mapping tests.

### PR 5/8 — Phase 3: Frontend and Localization

Branch: `feature/openrouter-provider-05-frontend`

Depends on PR 4.

Frontend scope:

- Add OpenRouter to LLM Settings provider values, labels, badge rendering, stories, and provider selection.
- Reuse the existing API-key form and secret-preserving edit behavior.
- Add OpenRouter-specific setup disclosure for account-scoped catalog, upstream routing, data handling, ZDR ownership, and manual catalog refresh after policy changes.
- Add natural localized copy for English, French, Japanese, and Korean.
- Preserve existing model-picker layout, search, pagination, sync, stale, and failure states.

Tests:

- Component and state projection tests where available.
- Static Storybook states for provider selection and setup disclosure.
- Locale JSON parsing and key parity.
- TypeScript format, lint, typecheck, app build, and Storybook build.

### PR 6/8 — Validation and E2E

Branch: `feature/openrouter-provider-06-validation`

Depends on PR 5.

Validation scope:

- Extend deterministic model-listing fixtures only as needed to express OpenRouter known and unknown publishers, missing LiteLLM metadata, capabilities, and invalid candidates.
- Add public API E2E for provider discovery, secret-safe CRUD, initial catalog lifecycle, direct projection, sync failure/retry, pagination/search, and Agent/Workspace model snapshot selection.
- Add Web Surface E2E when existing model-settings coverage can verify the OpenRouter setup disclosure and model-picker lifecycle without new infrastructure.
- Run the complete planned backend, generated-client, frontend, and credential-free E2E matrix.
- Record commands, environment constraints, results, and any implementation fixes in the PR description.
- Compare the implementation strictly against the design and current specs.

Optional live scope:

- If an operator-provided OpenRouter key is available through a safe prerequisite snapshot, run authenticated account catalog and representative Responses smoke tests marked `live_external`.
- Live verification is not a required CI dependency and does not retain credentials, prompts, responses, or account policy values.

### PR 7/8 — Spec Promotion

Branch: `feature/openrouter-provider-07-spec`

Depends on PR 6.

Documentation scope:

- Run spec review against the full implementation diff.
- Add `docs/azents/spec/flow/openrouter-api-key.md`.
- Update `docs/azents/spec/domain/model-catalog.md` for OpenRouter integration scope, direct projection, capabilities, and sync behavior.
- Update other living specs only when the implementation changes their generic behavior.
- Mark the design implemented with the verified implementation date.
- Change ADR-0169 from Draft to Accepted only after implementation and validation are complete.

Validation:

- Living-spec frontmatter, code paths, versions, changelogs, and generated indexes through pre-commit.
- Strict spec-to-code comparison with no undocumented shipped behavior.

### PR 8/8 — Cleanup

Branch: `feature/openrouter-provider-08-cleanup`

Depends on PR 7.

Contents:

- Remove this temporary implementation plan after specs are current and the design is marked implemented.
- Remove only plan-specific stale references.
- Do not include runtime changes, refactors, or new behavior.

Validation:

- Documentation validation through pre-commit.
- Full stack relationship and clean working tree check.

## Dependency Order

```mermaid
flowchart LR
    D[1 Design] --> P[2 Plan]
    P --> C[3 Provider and catalog]
    C --> R[4 Runtime]
    R --> F[5 Frontend]
    F --> V[6 Validation and E2E]
    V --> S[7 Spec promotion]
    S --> X[8 Cleanup]
```

The stack is merged from front to back only. If an earlier phase changes after later branches exist, rebase the dependent branches with the repository stacked-PR workflow before merging.

## E2E Primary Validation Matrix

| User-visible behavior | Deterministic path | Expected result |
|---|---|---|
| Provider discovery | Public provider capability API | Stable `openrouter`, `api_key`, not experimental |
| Secret-safe CRUD | Public integration CRUD with fake key | Create/list/get/update responses never expose the key |
| Initial catalog creation | Create integration using deterministic listing marker | Integration catalog exists and publishes a successful snapshot |
| Unlimited account model exposure | Deterministic OpenRouter listing with known, unknown, and LiteLLM-missing models | Every valid text-output candidate is selectable |
| Invalid listing entries | Deterministic mixed valid/invalid listing | Valid models publish; invalid items contribute bounded skip diagnostics |
| Account failure state | Deterministic failure variant | Integration remains created and picker reports failed-without-snapshot or stale-snapshot warning |
| Explicit catalog retry | Public sync endpoint after deterministic failure/state change | Existing cooldown/block rules apply and successful retry publishes a snapshot |
| Search and pagination | Public catalog entry list | OpenRouter uses shared search, limit, offset, and total-count semantics |
| Agent model selection | Public Agent create/update through catalog id and exact model id | Snapshot stores `provider=openrouter`, exact id, developer, capabilities, and runtime metadata |
| Workspace defaults | Public Workspace model settings update | Same catalog normalization and snapshot semantics as Agent selection |
| Unknown publisher safety | Deterministic unknown publisher model | Developer is `other`; no Anthropic cache/tool behavior |
| OpenRouter web search | Backend request lowering plus optional Web Surface selection | Capability is selectable, opt-in, and lowers to `openrouter:web_search` |
| Setup disclosure | Story/Web Surface | UI identifies external routing and data-policy ownership without claiming ZDR |
| Provider execution errors | Mocked Responses transport | Bounded common provider failure presentation and existing retry lifecycle |

## Fixture and Prerequisite Support

### Required credential-free fixture

Reuse the existing deterministic integration model-listing mechanism selected through the integration name. Extend provider-specific fixture construction if necessary so OpenRouter cases can represent:

- known publisher id such as `anthropic/example-model`;
- unknown publisher id such as `new-publisher/example-model`;
- a valid candidate absent from LiteLLM metadata;
- text and image input metadata;
- function tools, parallel tools, reasoning, web search, and generation parameter metadata;
- invalid candidates for skip diagnostics;
- deterministic provider listing failure.

The fixture is reached through normal public integration and catalog APIs. No test inserts, updates, or deletes product rows directly.

### Optional live prerequisite

An OpenRouter key may be exposed to live E2E only through the repository's safe prerequisite preparation boundary. The prerequisite snapshot records readiness metadata only. A missing key skips optional scheduled verification and fails only when a maintainer explicitly requests live verification.

## Quality Checks by Phase

### Backend phases

Run from `python/apps/azents`:

- `uv run ruff check --fix .`
- `uv run ruff format .`
- `uv run pyright`
- focused pytest suites for changed modules;
- full backend pytest before validation completion when environment prerequisites are available.

### Generated clients

- Dump OpenAPI through the project command/skill.
- Regenerate Python and TypeScript clients from stored specifications.
- Run generated Python client tests.
- Run TypeScript public-client format, lint, typecheck, and build/generation consistency checks.

### Frontend phase

Run from `typescript`:

- `pnpm run format`
- `pnpm run lint`
- `pnpm run typecheck`
- `pnpm run build --filter=@azents/web`
- relevant component tests and Storybook build.

### E2E phase

Run from `testenv/azents/e2e`:

- focused OpenRouter public API tests;
- required credential-free deterministic lane or the relevant focused subset;
- Web Surface E2E when added;
- optional `live_external` subset only with prepared credentials.

## Error and Security Validation

The validation phase must explicitly confirm:

- keys are encrypted and absent from public responses, logs, failure messages, snapshots, and test evidence;
- a workspace user cannot control the OpenRouter API origin;
- `HTTP-Referer` is absent by default;
- `X-OpenRouter-Title` contains only the static application name;
- listing failures use catalog attempt state rather than unhandled product 5xx responses;
- inference failures use the common bounded provider-failure contract;
- unknown publishers cannot activate Anthropic cache-control or hosted-tool dialects;
- OpenRouter account routing and privacy settings are not duplicated or weakened by request overrides.

## Spec Impact Candidates

Required:

- `docs/azents/spec/domain/model-catalog.md`
- new `docs/azents/spec/flow/openrouter-api-key.md`

Conditional after full diff review:

- `docs/azents/spec/domain/agent.md`
- `docs/azents/spec/flow/agent-execution-loop.md`

No current-behavior spec is modified before implementation and validation establish the shipped behavior.

## Rollout

- Apply the additive PostgreSQL provider enum migration before accepting OpenRouter integration writes.
- Deploy backend and regenerated API clients before or with the frontend provider option.
- Existing workspaces require no backfill.
- New and updated OpenRouter integrations populate their account catalog through the existing background sync lifecycle.
- Rollback hides/disables the provider but leaves the PostgreSQL enum value in place.
- Existing Agent snapshots remain readable; they cannot execute if the OpenRouter integration/runtime is unavailable after rollback.

## Blockers and External Actions

Required implementation has no known external blocker.

Optional live verification is blocked without an operator-provided OpenRouter key and must not delay credential-free implementation or required CI. Any live schema or runtime discrepancy found before completion is fixed in the responsible phase and rebased through the remaining stack.

## Completion Criteria

The feature is complete when:

- all eight PRs exist in the correct stack order;
- implementation matches ADR-0169 and the approved design;
- required unit, generated-client, frontend, migration, and credential-free E2E checks pass;
- living specs describe shipped behavior;
- the design is marked implemented and ADR-0169 is Accepted;
- the temporary implementation plan is removed in the cleanup PR;
- every required GitHub CI check passes on every open PR in the stack;
- no PR has been merged without explicit user approval.
