---
title: "Catalog Capability Correction Implementation Plan"
created: 2026-10-03
tags: [model-catalog, backend, engine, testing]
---

# Catalog Capability Correction Implementation Plan

## Confirmed repair requirements

The requester instructed on 2026-10-03 KST: hotfix ChatGPT GPT web search first,
then comprehensively investigate additional omissions and correct them in stacked
PRs. Restore justified existing behavior without reintroducing rejected inference.

- Restore ChatGPT OAuth web-search support through final catalog publication,
  saved capability decoding, configuration validation and request lowering.
- Audit every supported provider and capability dimension through actual ingress,
  projection, persistence-facing serialization, API/UI and execution consumers.
- Distinguish approved removals from defects; fix reproduced omissions and cover
  adapter-to-consumer boundaries rather than only intermediate helper values.
- Preserve exact identities, explicit denial/null/empty, saved selections, existing
  ownership, no-source operation and unavailable-price behavior.
- Create the full stack before waiting on CI. No merge or production operation.

## Authority and readiness

- [Requirements](../requirements/capability-261002-evidence-backed-model-support.md):
  REQ-1–8 remain confirmed; especially general recovery and regression accountability.
- [ADR](../adr/capability-261002-evidence-backed-model-support.md): D1–D3 remain unchanged.
- [Approved Design](../design/capability-261002-evidence-backed-model-support.md):
  revision 2, M1–M13 approved by requester. Repairs implement the existing baseline.
- [Current Spec](../spec/domain/model-catalog.md): route-bounded built-ins, provider
  ownership and saved selection authority. Existing ChatGPT built-in policy in
  `core/builtin_tools.py` authorizes web search independently of optional pricing.
- Design delta: None. Any unsupported new material behavior is excluded.
- Baseline: `a500f759427da66c1795e1c160d63783bf6dd0ec`.

## Delivery phases

1. `Catalog capability repairs [1/2]: restore ChatGPT web search` — minimum hotfix,
   final-entry and request-path regressions, current Spec clarification.
2. `Catalog capability repairs [2/2]: close audited capability omissions` — grounded
   additional corrections, full provider/consumer audit evidence, combined validation,
   Spec promotion and removal of these temporary plans.

The second phase depends on the first PR being open. Read-only audit discovery may
proceed while phase 1 is implemented, but phase-2 code begins only after phase 1 PR.
Increase the phase count only if audit findings require a separate reviewable boundary.

## Ownership and context

- Root `/root`: all repository edits, integration, validation, commits, PRs, CI and
  correction requests. No conflicting file ownership.
- `/root/catalog-capability-parity-audit`: read-only ingress/source/projection audit.
- `/root/catalog-tool-parity-audit`: read-only saved/API/UI/runtime/context/cost audit.
- Single exact independent reviewer: `/root/catalog-metadata-reviewer`. Root requests
  review only after each complete integrated phase and root validation are stable.

## Audit and validation matrix

Cover all ten `LLMProvider` values and context/default/input/output limits, reasoning
and effort completeness/defaults/summaries, function/parallel/strict support,
structured responses, request parameters, modalities, provider-hosted and client
built-ins, execution options and captured context/cost. Compare pre-cutover
`5710489a4^`, current code and approved intent; never restore old profile/name/price
inference just to match historical output.

Root validates focused Python adapter/projection/save/profile/lowerer tests, real SDK
HTTP serialization with MockTransport, Ruff/format/ty, relevant frontend tests when
affected, assembled credential-free E2E where required, documentation validation and
full stack CI. Fixtures use synthetic credentials; no live provider or production
database write is required. Preserve command/results/environment and failure evidence
in the Session and a final supporting verification report.

## Removal, rollout and cleanup

Phase 1 removes the accidental omission at the final semantic producer, not the
data-only source or historical decoding contracts. Later corrections remove faulty
units in their owning phase. No new fallback, alias, automatic reselection or schema
migration is planned. Existing bad published catalogs require ordinary refresh after
an authorized release; saved selections change only through explicit reselection.
Delete this plan and both phase plans after integrated validation and Spec promotion.
