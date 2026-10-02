---
title: "Model Support Phase 3: Cutover and Final Verification"
created: 2026-10-03
tags: [model-catalog, backend, engine, implementation, migration]
document_role: supporting
document_type: phase-plan
snapshot_id: capability-261002
---

# Phase Execution Plan

- Phase: 3 of 3, SQL-only cutover fencing and complete-stack verification.
- Branch/base: `feat/catalog-261002-3-cutover` -> `feat/catalog-261002-2-connection` at `01d51ee97` (PR #2064; foundation #2059).
- PR boundary: final writer-contract migration, relational pointer integrity, deterministic E2E source conversion, final product verification, Spec promotion and temporary-plan cleanup. No intermediate production release.
- Inputs: phase-2 reviewer-clear F1–F3, root whole backend 7,721 passed / 3 skipped, whole ty/Ruff/format, web 335 tests / four Storybook states, generated-interface and real captured-source replay checks.
- Deliverables: preserve old catalogs/selections/costs while retiring only genai current source authority; reject old writers and old candidate reuse; enforce deferred current-pointer existence and publication ownership; prove source absence/recovery and stored-contract request/cost behavior without production credentials.
- Non-goals: production migration/source publication/deployment, cluster mutation, PR merge, binary-only rollback, payload decoding or remote collection in migration, new unknown-state/source mode, OAuth work, new tools or model-name patches.
- Approved Design mechanisms: M5/M9/M11–M13 and final verification of M1–M10. Authority: capability-261002 REQ-1–8, ADR-D1–D3, approved Design revision 2 sections 11–14 and unchanged catalog ownership/lifecycle.
- Design delta: None.
- Removal obligations: freeze retired source writes/publication; replace old E2E source URL/provider-price fixture; retire obsolete active-authority seeds/assertions; replace current Spec's old active metadata/pricing claims; remove temporary phase plans only after full verification/promotion. Preserve immutable historical snapshots/migrations, historical genai columns/data and descriptor-absent selections.
- Absence verification: old SQL-shape writer/candidate rejection, no network/decoder in upgrade, source absence allowed, scans for active direct genai import/config/calc/match authority, poisoned pricing/updater entrypoints, final Spec/code-path validation.

## Fixed Interfaces and Migration Contract

Generate the migration through `alembic revision` from current head `459a4285993c`; update the revision file. The migration uses static SQL contract constants rather than importing application decoders/services. Table locks have one documented fixed order and pointer preflight precedes mutations; the transaction installs the fence atomically.

Preserve old catalog current pointers, entries, Agent/Workspace selections and recorded costs. Clear only `genai_prices` current source pointer; ensure the new source authority exists with no current snapshot. Terminalize retired running source attempts with bounded migration diagnostics. Do not fetch, decode or calculate old/new metadata in upgrade.

Reject retired authority insert/update/delete and new/updated/deleted retired source snapshots; retain history. Admit new source writes/pointers only for the adopted key/kind/schema. Conversation candidates require projection schema `2`, null active genai provenance and a matching new source if supplied; system source is required, integration source optional. Image-generation purpose remains exempt.

On conversation current-pointer change, verify target existence, same catalog owner, projection version and source contract; reject clearing an existing successful pointer. An unchanged old pointer may accompany operational updates. Validate reused old candidates at publication, not only insert. Retired source attempts can fail but cannot publish new success.

Add deferred `NO ACTION` current-pointer FKs, preserve replace-pointer-then-delete-superseded transactions and parent catalog/integration cascades. Reject referenced snapshot deletion and source deletion stripping provenance through `SET NULL`; do not blanket-prohibit all superseded catalog snapshot deletion. Preflight inconsistency fails visibly rather than deleting/nulling catalog data. Default downgrade raises an irreversible-contract error without partial guard removal.

## Ownership

Paths are repository-relative. Owners do not edit other lanes concurrently.

| Workstream | Owner | Owned paths | Depends on | Output and validation |
| --- | --- | --- | --- | --- |
| SQL fence and ORM integrity | `/root` | new generated `python/apps/azents/db-schemas/rdb/migrations/versions/*` migration only, `db-schemas/rdb/revision`, `src/azents/rdb/models/{llm_catalog,model_metadata_source}.py` | fixed phase-2 contract | SQL-only atomic guards, deferred FKs and model/schema alignment; root migration/full-backend checks |
| Migration and backend regression fixtures | `/root/catalog-snapshot-recovery-audit` | new `python/apps/azents/src/azents/repos/llm_catalog/data_source_cutover_test.py`, existing `repos/llm_catalog/repository_test.py` active-authority fixtures only, related migration test assertions only when root assigns | generated new revision ID and SQL contract | disposable PostgreSQL old-only/no-network upgrade, writer/candidate/pointer/deletion/downgrade matrix; preserve historical migration intent |
| Deterministic source fixture | `/root/catalog-capability-parity-audit` | `testenv/azents/e2e/src/support/image_generation_openai_proxy.py` source-payload function only, `src/tests/conftest.py` source URL wiring only, focused Docker-free source fixture support test | new source decoder and estimator | inert exact-scoped JSON source and per-token rates preserving fixture arithmetic; no public network/credentials or fixture DB writes |
| Product E2E | `/root/capability-ui-implementation` | `testenv/azents/e2e/src/tests/required/public/test_per_prompt_inference_profile.py` and a focused `test_model_support_contract.py` if needed; no proxy/backend edits | fixture handoff and fence | representative refresh/picker/save/saved-contract dispatch/cost and refresh-after-save preservation through existing APIs; actual execution by root after handoff |
| Final integration, Specs and release preparation | `/root` | affected current `docs/azents/spec/**`, approved snapshot implemented markers after verification, useful supporting rollout/QA record, phase-plan cleanup, generated artifacts if changed | all implementation lanes stable | `/spec-review` once, final backend/migration/TypeScript/E2E validation, exact reviewer, PR and all-stack CI monitoring |

The exact single independent reviewer remains `/root/catalog-metadata-reviewer`. Root requests complete stable phase-3 review after all workstreams and root integrated validation. Only material corrections require targeted re-review.

## Integration and Validation

1. Root creates SQL migration/revision and shares its exact ID; fixture/E2E owners can work independently on approved source/consumer contracts.
2. Test owner seeds historical SQL shapes below the new revision and proves upgrade without source success/network. Complete pointer/source/candidate/attempt/deletion/cascade/irreversible-downgrade matrix. Convert only obsolete active-authority fixtures; historical writer tests remain historical evidence.
3. Root integrates lanes, runs focused and whole backend ty/Ruff/pytest plus dedicated migration tests, source fixture support tests, TypeScript checks and generated/absence scans.
4. Run representative local required E2E through fresh branch-matched product images/fixtures and ordinary API setup. No direct E2E database writes, production credentials or live provider prerequisite bypass. Capture JUnit/logs and SDK/proxy request evidence; credential-free core cases fail rather than silently skip.
5. Run `/spec-review` once before final QA; replace current Spec claims/code paths with the reached implementation. Add identical KST implemented dates to Requirements/Design only after complete verified implementation, preserving accepted ADR history. Record drain/recovery prerequisites and final commands/results in a useful supporting record.
6. Freeze the full phase-3 diff, request exact reviewer, correct findings and rerun affected root checks; then remove temporary plans and verify docs/references. Commit/open third stacked PR. Only after all three PRs exist monitor complete-stack CI and own corrective work through completion. Do not merge or apply production changes.

## Release, Scope and Checkpoint

The complete stack is one replacement release. DB guards cannot revoke old in-memory captures or prevent an old save producer from stripping additive fields. Release preparation must drain/stop old save/dispatch/source producers before exposing v2, apply SQL-only fencing, then activate new producers and let normal refresh collect the new source. First-fetch failure leaves old catalogs readable and optional costs unavailable; retry/forward correction is normal recovery. Binary-only rollback is unsupported; separately authorized stopped-writer schema/data restoration is required for emergency reversal. Do not promise arbitrary mixed-version safety or zero rollout interruption.

Scope-drift check: no new source/compatibility/authorization mode, inference remapping, dual reads, live rollout or historical document rewrite. Plans create no authority. A true material change returns to feature design; local corrections remain within approved mechanisms.

Context checkpoint: record revision/branch/PR, SQL guards/FKs, old data preservation, actual migration/E2E/QA evidence, Spec promotion and remaining release prerequisites. Phase 1/#2059 and phase 2/#2064 remain unmerged stack inputs; current delivery plan requires PR creation before the next phase, not a root-performed merge. Operational drain/production release remains an external prerequisite and is not executed here.
