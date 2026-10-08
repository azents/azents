---
title: "Model Support Cutover Verification and Release Prerequisites"
created: 2026-10-03
tags: [model-catalog, migration, verification, release]
document_role: supporting
document_type: supporting-verification-report
snapshot_id: capability-261002
---

# Scope and Authority

This report records implementation evidence and release prerequisites for the
approved [capability-261002 Design](capability-261002-evidence-backed-model-support.md),
revision 2 / M1–M13. It does not authorize production operations or add Design
mechanisms. Design delta: None.

The complete three-PR stack is one replacement release. Phase 1 provides the
inert source/support contract; phase 2 connects projection/runtime/UI/pricing;
phase 3 installs the writer fence and final verification. No connection-only
intermediate release, production source prefetch, database mutation, deployment
or PR merge was performed by this development task.

## Local Verification Environment

- Worktree: the Session's Azents checkout, final cutover branch based on phase-2
  commit `01d51ee97`; tests consume the pinned project dependencies.
- Backend/migration tests use disposable local PostgreSQL containers. The dedicated
  migration runner explicitly unsets `AZENTS_MIGRATION_TEST_DATABASE_URL` to avoid
  an external database override.
- Required product E2E uses branch-matched server, Runtime Runner and Docker Runtime
  Provider images, built from the current worktree, plus deterministic local SDK
  proxy data. The server image's revision file was checked as `c8bc0a5dcab0`.
- No external provider credentials, browser/cookie prerequisites or production
  resources are required for these cases. E2E setup and mutations use public/admin
  APIs and bounded local fixture controls, not direct product database writes.

## Verified Behaviors

### Source and saved support

The captured public-data replay decoded/restored 4,451 models across 134 namespaces.
Source/parser/identity tests distinguish missing/null/false/empty evidence and
native/OAuth/cloud identities. Native OpenAI/ChatGPT profile APIs are poisoned in
focused tests; exact xhigh/max wire values survive official SDK MockTransport.
Saved v2 predicates remain separate from conservative display views. Configurable
potential does not authorize dispatch: actual final JSON-function declarations and
effective effort determine client/hosted predicates. Explicit incompatible strict
requests reject instead of becoming false. Historical descriptor absence remains
unchanged.

### Pricing removal and capture

The typed estimator freezes exact identity, source hash, rules, revision and aware
time once. Specialized cache/media/tool quantities, context thresholds, tiers and
off-peak windows require complete applicable evidence. Seven installed genai price
and updater entrypoints were poisoned while new capture/estimation passed; the
legitimate transitive Pydantic usage extractor still returned counters. No direct
LiteLLM/genai execution import, package-bundled pricing fallback or request-time
source fetch is an Azents authority.

### SQL-only cutover

Revision `c8bc0a5dcab0` follows `459a4285993c`. It locks sources, source snapshots,
catalogs, catalog snapshots and attempts in that order. Preflight verifies pointer
existence/ownership and requires replacement current authority to be inactive;
unexpected active replacement state fails atomically rather than clearing its data.
The only retired current source pointer cleared is `genai_prices`.

Disposable-PostgreSQL coverage proves no HTTP/application decoder is used by upgrade,
old catalog pointers/entries, Agent/Workspace selections and event cost JSON survive,
retired running attempts fail, old writes/publication/reuse reject, compatible new
source/candidate contracts are admitted, image purpose remains exempt and unchanged
historical pointers accept operational updates. Ownership/type changes cannot bypass
publication checks. Deferred `NO ACTION` pointers/provenance prevent dangling or
stripped references while permitting replacement then superseded deletion and parent
cascades. Default downgrade rejects before guard removal.

### Product E2E

The representative system-source flow refreshes a real catalog/picker, saves a
Workspace selection and creates an Agent from it. Native max is sent unchanged at
baseline cost 0.000003 USD. After source/catalog refresh, saved Agent/Workspace JSON
and max authorization remain unchanged while the next operation uses 0.000007 USD.
Removing the exact source row leaves saved execution usable and cost unavailable.
Explicit reselection adopts the new subset: max fails admission without an input
event, while xhigh remains exact on the wire. Baseline fixture state is restored.

## Executed Checks

- Phase-2 final whole backend: **7,721 passed, 3 skipped**; whole ty/Ruff/format and
  exact independent correction reviews cleared F1–F3. Web: **335 passed**, full
  TypeScript workspace typecheck, lint/format and four Storybook interaction states.
- Phase-3 preliminary whole backend: **7,771 passed, 3 skipped**, six existing warnings.
- Complete historical migration module + new cutover matrix + repository fixtures:
  **67 passed** (11 historical + 50 cutover + 6 repository). Dedicated Alembic
  checks: **12 passed**, including ORM/DDL agreement and irreversible boundaries.
- Docker-free source/fixture support suite: **350 passed**. Isolated `python -I -S`
  and actual Alpine image imports prove the proxy remains standard-library-only.
- Offline production source decoder/projection/estimator: **11 records** across
  baseline/refreshed/missing-model variants, including consumed media facts and
  unchanged per-token arithmetic.
- Representative product E2E: **1 passed**. Complete per-prompt and model-selection
  regression files: **29 passed**, using the same verified branch-matched images.
- OpenAPI/client generation produced no additional schema/client diff after the
  phase-1 public contract. Spec promotion is limited to current behavior/code paths;
  accepted ADR history and executed historical migrations are unchanged.

Focused commands use `uv run pytest` under `python/apps/azents`, and
`AZENTS_E2E_IMAGE_BUILD_PROFILE=required uv run pytest` under `testenv/azents/e2e`.
Logs, JUnit and image-build evidence are preserved in the development Session.
The exact single independent reviewer cleared phase 3 with no remaining grounded
material findings. Independent PostgreSQL matrix/repository/historical checks
passed 67 cases, dedicated Alembic checks passed 12 and a focused fixture set
passed 28; the reviewer inspected the actual product E2E artifacts without
reclassifying root-owned results as independent reruns. Full-stack required CI
remains an external submission gate until the final PR exists and CI completes.

## Failures Found and Corrected

- OpenRouter complete/unknown parameters initially became absent structured support:
  corrected presence-aware evidence and exact-source enrichment regressions.
- Conditional support was initially disabled by SDK/display and outer built-in gates:
  corrected codec representability and actual EngineAdapter dispatch predicates.
- Explicit strict true initially became false: corrected both lowerers with actual
  SDK request/no-HTTP negative cases.
- New SQL fixtures initially violated required count fields, authority/pointer order
  or duplicate authority initialization: repaired test seeds without weakening guards.
- A new fixture control imported Pydantic into the bare Alpine proxy: replaced it
  with a strict frozen stdlib decoder and added site-package-free import coverage.
- The new E2E selected an earlier title request because Main and Lightweight use the
  same model: polling now excludes the known title operation, without filtering on
  desired effort/output fields or hiding genuine main-request loss.

# Required Release Procedure

This is preparation guidance, not executed production work.

1. Verify a matching pre-transition schema/data backup and a release/deployment
   procedure that prevents an intermediate phase-2 image from serving requests.
2. Drain/stop old save, dispatch, source collection and catalog publication producers.
   Stop new old-binary admission and account for in-flight captures. Database guards
   alone cannot stop an old binary from stripping additive fields or calculating an
   already captured estimate; arbitrary mixed-version execution is unsupported.
3. Apply the SQL-only migration atomically with old producers inactive. Preflight
   failure is a visible operator issue; do not erase pointers or bypass guards to
   force success. No successful remote collection is a prerequisite.
4. Activate the complete compatible request/sync release, then let ordinary scheduled
   or administrator refresh collect the new source. Until success, catalogs remain
   readable and optional estimates/context enrichment follow no-source behavior.
5. Verify new-family publication, schema-2 candidate/current-pointer ownership,
   stored selection preservation and normal source/catalog attempt health. Initial
   fetch failure is recovered through retry/refresh or a corrected forward release.

Binary-only rollback is unsupported after the fence. Emergency return requires
separate authorization, stopped/drained producers and a verified matching schema/data
restoration procedure. Retained genai history is never automatically reactivated.
No production drain/migration/deployment verification is claimed by local test results.
