---
title: "xAI API Key Provider Historical Decision Reconstruction"
created: 2026-07-10
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: xai-260710
historical_reconstruction: true
migration_source: "docs/azents/design/xai-api-key-provider.md"
---

# xAI API Key Provider Historical Decision Reconstruction

- Snapshot: `xai-260710`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/xai-api-key-provider.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### xai-260710/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Credential Contract

**Options**

- Define an xAI-specific API-key secret type.
- Reuse the existing discriminated `ApiKeySecrets` contract.

**Decision**: Reuse `ApiKeySecrets(type="api_key")` with no provider config. The encryption, create/update semantics, blank-key edit behavior, and response redaction are identical to existing API-key providers.

### Explicit source section: Provider and Database Contract

Add `xai` to the `LLMProvider` enum and PostgreSQL `llm_provider` enum using a new generated Alembic revision. No existing migration is modified and no row backfill is required.

Map `xai` to:

- secret type: `api_key`
- config: none
- LiteLLM provider/model prefix: `xai/`
- model developer: `xai`
- system catalog source family: `xai`
- public display name: `xAI API key`
- experimental: `false`

### Explicit source section: CI and Skip/Fail Policy

- Backend enum, credential, CRUD, catalog, runtime mapping, and lowerer tests run in normal CI.
- OpenAPI generation and Python/TypeScript generated-client checks run in normal CI.
- Frontend format, lint, typecheck, build, and component/story coverage run in normal CI.
- Deterministic E2E uses fake credentials and must pass.
- Optional live verification skips when `XAI_API_KEY` is absent in scheduled exploratory runs. When a maintainer explicitly requests live verification, a missing key or failed current-model call is a failure.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
