---
title: "Catalog Correction Phase 1 Execution Plan"
created: 2026-10-03
tags: [model-catalog, backend, engine, testing]
---

# Phase Execution Plan

- Phase: 1 — ChatGPT web-search hotfix.
- Branch/base: `fix/catalog-261003-1-chatgpt-web-search` → `main`.
- PR boundary: restore existing ChatGPT route support in the final v2 capability
  producer, with actual adapter-to-entry and configuration-to-request regressions.
- Inputs: confirmed repair instruction and approved `capability-261002` baseline.
- Deliverables: source-independent ChatGPT web-search support survives serialization,
  final catalog entry production and saved request authorization; other provider
  unknowns remain conservative.
- Non-goals: additional provider corrections, metadata aliases, pricing-derived
  support, changing saved selections, automatic catalog refresh or deployment.
- Interfaces: unchanged v2 semantic schema and provider request APIs.
- Approved Design mechanisms: M2, M4–M6, M13.
- Authority references: capability-261002/REQ-1–5, REQ-8, ADR-D1, approved Design
  revision 2 and existing ChatGPT built-in registry contract.
- Design delta: None.
- Removal obligations: replace accidental loss of reviewed ChatGPT route policy.
- Absence verification: actual ChatGPT listing with absent web-search source metadata
  produces supported semantic and effective tool views; no price/source/name inference.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Hotfix | /root | core/model_capability_projection.py and its tests | existing policy | contract-derived route support | focused projection cases |
| Connected tests | /root | model_listing/provider tests, projection and engine tests | hotfix | final entries and request authorization | serialization, save validation, real SDK wire |
| Documentation | /root | model-catalog Spec, these plans | hotfix | exact correction boundary | docs validation |

- Integration order: reproduce with failing connected tests, implement the narrowly
  scoped route correction, run all focused suites/quality checks, update current
  Spec, freeze diff, request independent review, resolve findings, commit and open PR.
- Independent review: `/root/catalog-metadata-reviewer`, root-requested read-only.
- Final validation: root-owned Ruff, format, ty, adapter/projection/built-in/profile/
  lowerer tests and actual SDK serialization; assembled E2E in final stack QA.
- Scope-drift check: no new model facts, provider policy, source authority, public
  schema or saved-selection mutation. Preserve explicit listing denial/unknown
  if such evidence is supplied; route policy supplies only absent account evidence.
- Context checkpoint: phase-1 PR precedes phase-2 edits; provider/consumer audit
  reports are read-only inputs for the subsequent execution plan.
