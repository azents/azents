---
title: "Provider Compatibility Spec Sync Report"
tags: [backend, engine, documentation]
created: 2026-05-03
updated: 2026-05-03
implemented: 2026-05-03
document_role: supporting
document_type: supporting-validation-report
migration_source: "docs/azents/design/provider-compat-spec-sync-report-2026-05-03.md"
---

# Provider Compatibility Spec Sync Report

## Audit Scope

Cumulative diff range: `main...feat/provider-compat/phase4`

Primary changed files:

- `python/apps/nointern/src/nointern/engine/sdk/filters/**`
- `python/apps/nointern/src/nointern/engine/sdk/engine_adapter.py`
- `python/apps/nointern/src/nointern/engine/sdk/filters_test.py`

## Impacted Spec

| Spec | Category | Action |
|---|---|---|
| `docs/nointern/spec/flow/agent-execution-loop.md` | SPEC-UPDATE-NEEDED | Add request compatibility filter stage in spec promotion PR |

## SPEC-UPDATE-NEEDED Draft

Reflect the following in `agent-execution-loop.md`.

- Add `ProviderCompatibilityFilter` as final stage of SDK request filter chain.
- Provider/model compatibility applies only to request payload without changing DB events.
- Responses `store=False` id stripping, foreign provider metadata stripping, tool call id normalization, and unsupported media fallback are performed as request-only transforms.
- Schema/options sanitizer is helper-based, and provider adapter wiring extension is follow-up candidate.

## ADR Candidates

- Handle provider compatibility as request-only deterministic transform.
- Handle tool id compatibility by deterministic rule, not stateful mapping.

Do not auto-generate ADR; keep only candidate list.
