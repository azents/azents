---
title: "Catalog Correction Phase 2 Execution Plan"
created: 2026-10-03
tags: [model-catalog, backend, engine, frontend, testing]
---

# Phase Execution Plan

- Phase: 2 — comprehensive omission audit and grounded corrections.
- Branch/base: `fix/catalog-261003-2-capability-omissions` → `main` after the
  requester independently merged phase 1 (#2072). The original dependency was
  `fix/catalog-261003-1-chatgpt-web-search`; its corrections remain included.
- PR boundary: evidence-backed fixes, full coverage ledger, integrated QA and current
  Spec updates. The separate third phase owns existing top-k interface propagation
  and final temporary-plan cleanup.
- Inputs: phase 1 PR #2072 at `5a9195352`, confirmed repair instruction, approved
  capability-261002 revision 2, three read-only commit-pinned audits.
- Deliverables: account/source-supported choices survive actual final producers
  and consumers without omitted SDK fields or unsupported profile ceilings.
- Non-goals: new provider policy, controls or sources, old name/price/profile
  inference, saved-selection rewriting, schema change, merge or production writes.
- Interfaces: current v2 semantic descriptor, existing selectable options and
  request settings, installed public SDK codecs and extra-body extension.
- Approved Design mechanisms: M1–M13, only their existing approved obligations.
- Authority references: capability-261002/REQ-1–8, ADR-D1–D3, approved Design
  revision 2, current model-catalog and engine Specs.
- Design delta: None.
- Removal obligations: replace confirmed faulty projection/wire units. The final
  third phase removes the execution plans.
- Absence verification: reproduce defects before changes, preserve negative,
  unknown and explicit-empty controls, assert actual final JSON/request output;
  scan for excluded source/library authority and stale plan references.

## Grounded initial correction scope

1. Preserve reviewed client-image capability on a source-declared Responses
   conversation route; source mode is not a reason to disable its function executor.
2. Bound explicit Google effort facts by the actual installed codec domain, including
   its documented representable defaults when a profile omits an optional level set.
   Transport representability alone never creates model effort evidence.
3. Preserve saved-authorized explicit sampling parameters through compatible
   Responses/Chat SDK encoding instead of the SDK's generic reasoning-model filter.
   Keep reasoning settings, actual conditions and unsupported rejection unchanged.
4. Complete the audit of native parallel-call handling, hosted image evidence,
   function/strict/default/media semantics and source/pricing/publication contracts.
   Add further corrections only for reproduced, approved-contract omissions; record
   intended exclusions and pre-existing unrelated deficiencies separately.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Audit inputs | read-only audit agents | Session audit reports only | pinned baselines | all-provider/field and consumer/source ledgers | local synthetic repros, code/authority references |
| Producers | /root | core/model_capability_projection.py, source/evidence ingress and tests as grounded | audit evidence | corrected semantic/effective views | actual adapter-to-entry and presence/scope matrix |
| Consumers | /root | engine/events and provider assembly with tests as grounded | producers, saved contract | exact authorized wire values | official SDK MockTransport and configuration/dispatch cases |
| QA and Spec | /root | relevant Spec, tests and supporting report | integrated changes | full coverage/results and cleanup | whole backend/quality, relevant frontend/product tests, docs, stack CI |

- Integration order: finish per-finding reproduction, fix in owning units with
  negative cases, close every audit ledger cell, integrate, run root-owned QA, promote
  current Specs, freeze diff, request review, resolve material findings, commit and
  open phase 2 PR. Then complete phase 3 before monitoring all three PRs.
- Independent review: `/root/catalog-metadata-reviewer`, the same single read-only
  reviewer; root requests only after stable complete integration and validation.
- Final validation: root-owned whole backend pytest/Ruff/format/ty; actual SDK wire
  tests for all affected dialects; relevant frontend checks; assembled credential-free
  product E2E supported by existing fixtures. Distinguish mock encoding from live
  provider acceptance; do not add production endpoint/auth mechanisms just for tests.
- Scope-drift check: fixes restore confirmed evidence/route semantics; unsupported
  old heuristics and new material behavior remain excluded. Audit findings do not
  create authority. Historical snapshots/migrations and saved choices are immutable.
- Context checkpoint: audit coverage, each defect and classification, invalidated
  validation, owning paths and current risks are recorded continuously in the Session.
  The supporting verification report consolidates the audit; final phase 3 deletes
  temporary plans without rewriting implemented Requirements/ADR/Design.
