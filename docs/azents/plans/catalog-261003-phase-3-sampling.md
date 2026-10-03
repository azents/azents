---
title: "Catalog Correction Phase 3 Execution Plan"
created: 2026-10-03
tags: [model-catalog, backend, engine, testing]
---

# Phase Execution Plan

- Phase: 3 — existing top-k and SDK sampling no-loss correction.
- Branch/base: `fix/catalog-261003-3-sampling-propagation` → `fix/catalog-261003-2-capability-omissions` (#2076, `db49c3392`).
- PR boundary: existing Agent parameter reaches the actual SDK unchanged or fails explicitly on an unrepresentable codec; final Spec promotion and temporary-plan cleanup.
- Inputs: completed phase-2 audit/review/QA, existing `ModelParameters.top_k`, approved capability-261002 Requirements/ADR/Design revision 2 and current Specs.
- Deliverables: nullable explicit internal carrier, verified Google/Anthropic/Bedrock wire, retained compatible sampling semantics and unsupported-route failure.
- Non-goals: public field/UI addition, new support facts, sources, heuristics, preset inheritance, migration, saved-object rewriting, merge or production changes.
- Interfaces: existing Agent parameter object and typed support validation; internal RunRequest/lowerer constructors; installed public SDK codecs and profiles.
- Approved Design mechanisms: M4–M6 and existing no-loss obligations of M10–M13.
- Authority references: capability-261002/REQ-1–8, ADR-D1–D3, approved Design revision 2; existing Agent model-parameter and Engine dispatch Specs.
- Design delta: None.
- Removal obligations: replace missing carrier links and stock warning-only sampling removal. Remove all catalog-261003 execution plans after complete validation and Spec promotion.
- Absence verification: all constructors explicitly carry nullable top-k; unsupported/native and missing Bedrock mappings fail before HTTP; selected controls do not disappear; no references to deleted plans remain.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Carrier | /root | engine/run/contracts.py, resolve.py, events/engine_adapter.py, all lowerers and callers | phase 2 | exact top-k at request boundary | resolve/worker/adapter/lowerer regression, whole ty |
| Wire preservation | /root | engine/providers/model_profiles.py, events/pydantic_ai_adapter.py, affected SDK tests | carrier | real native encoding or explicit failure | Google/Anthropic MockTransport and Bedrock botocore bodies, saved conditions |
| QA and cleanup | /root | affected Specs, supporting verification report, catalog plans | integrated code | independently reviewed final stack | root whole backend/quality, deployed relevant E2E, docs/absence, CI |

- Integration order: add required carriers and audit all callers; preserve validated sampling through installed codecs; add exact wire/denial tests; integrate and run root QA; freeze and request read-only review; batch findings and affected validation; targeted re-review only when required; promote Specs; remove plans; commit/open PR; monitor both follow-up PRs.
- Independent review: `/root/catalog-metadata-reviewer`, unchanged single reviewer, root requests review after stable complete integration.
- Final validation: root-owned Ruff/format/ty, focused and whole backend tests, required per-prompt/model-selection local deployed E2E, documentation catalog and diff checks; exact synthetic SDK bodies are not live-provider acceptance.
- Scope-drift check: no canonical top-k encoding is invented for OpenAI/native/compatible routes; actual Bedrock family encoding alone does not assert model support; accepted/unknown controls reach provider failure boundary while saved denials remain denied.
- Context checkpoint: record exact changed interfaces, test commands/results, remaining risks, reviewer result, removal evidence and release boundary in Session and supporting report. Plans remain temporary and are deleted in this final phase after validation.
