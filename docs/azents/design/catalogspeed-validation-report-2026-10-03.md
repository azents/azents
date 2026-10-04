---
title: "Current Model Catalog Validation"
created: 2026-10-03
updated: 2026-10-04
tags: [model-catalog, pricing, validation]
document_role: supporting
document_type: supporting-validation-report
---

# Current Model Catalog Validation

This report records implementation evidence for [catalogspeed-261003](catalogspeed-261003-current-model-data.md), Design revision 2, M1-M9. It does not introduce product or Design authority. Design delta: None.

## Environment and Boundaries

- Implementation baseline: `359bc0ff9`; branch: `refactor/catalog-latest-pricing-261003`.
- Backend checks use the frozen backend environment and disposable Docker PostgreSQL/Redis fixtures, never a production database.
- Public/admin OpenAPI and Python/TypeScript clients were regenerated from the implementation's API schemas.
- Frontend interaction evidence uses the actual application components in Storybook and Chromium.
- No production migration, cluster mutation, deployment, or PR merge is authorized or performed by this work.

## Current Evidence

- Root complete backend matrix after review corrections: 9,127 passed, 3 skipped. An affected catalog/migration/service rerun after schema/receipt corrections passed 151 tests; final corrected current-data conversion tests separately passed 22 cases.
- Separate migration matrix: 20 passed, including single linear head, full upgrade, and SQLAlchemy metadata/DDL alignment. An inherited image-entry integration FK omitted from the refactored mapping was restored after the alignment test identified it; historical alignment tests now follow the current head without moving their historical revision.
- Focused historical/current migration regression: 85 passed, including 22 current-data cases.
- Required E2E support tests after current-contract fixture corrections: 555 passed. The E2E package type checker and package Ruff lint/format pass against regenerated clients.
- Image selection component tests: 26 passed; nine real Chromium Storybook interaction states succeeded. Existing common input-description contrast warnings remain; no interaction failures occurred.
- Backend Ruff lint/format and whole-project `ty` pass after migration corrections.
- Root fresh TypeScript matrix bypassed Turbo cache: all workspace type, lint, and formatting checks passed; both product app builds passed. Main-web unit tests: 347 passed.
- Generated Python clients compile and import their current-contract models; the public selection schema carries pricing, current catalog schemas expose success/sync facts, and image responses expose usability.

## Migration Corrections and Coverage

Tests exposed and corrected operation outcome `candidate_ordinal` handling, deferred foreign-key trigger flushing before destructive DDL, and parent Workspace scope checks during missing-price initialization.

Coverage includes current-only source/catalog transfer, stable surviving entry identities, Decimal precision, exact account/provider/Workspace matching, missing-key-only price initialization across saved mirrors and future operation candidates, pending Historical Memory candidates, preservation of active/completed physical/history data, current owner/purpose/source guards, invalid legacy ownership rejection, old-work quiescence, purpose-specific image invalidation, obsolete schema/metadata receipt removal, and irreversible downgrade refusal.

The schema conversion clears obsolete current owner/entry/sync receipts, including nested hashes and the old hash-shaped producer-version tag. Historical event/cost/terminal operation JSON is not rewritten. Future ordinary reads do not fill prices or restore source history.

## Active-Path Absence Evidence

Bounded source/catalog/runtime searches and focused context tests verify:

- No active source/catalog snapshot graph, append-only catalog attempt history, source hash/fingerprint authority, candidate publication/cutover contract, or pricing whole-source capture remains.
- Physical price capture reads only the selected candidate's embedded definition and aware call time, with zero source database reads, whole-source decoding, or hashing.
- Optional context reads group only exact keys missing saved maxima and project only maximum-input-token evidence under the current source owner lock.
- Conversation selection predicates are unchanged; image generation uses the purpose-specific usability state.
- Executed historical migrations, immutable historical JSON, unrelated Runtime/VFS hashes, and internal code/protocol versions are outside the catalog-removal boundary.

## Capture Microbenchmark

A standalone CPU replay normalizes one synthetic OpenAI model once, then calls `capture_model_pricing` 20,000 times for each of seven samples, using an aware timestamp and the same saved definition. Median capture time was **1.194 microseconds**; the serialized definition was 428 UTF-8 bytes. Per-capture source reads, whole-source decodes, and hash calls are zero by construction of the pure capture function.

This is a microbenchmark of the replaced local capture work, not an end-to-end Worker latency measurement or provider-generation speedup claim. A prior whole-source replay used a different workload and is not a like-for-like denominator. End-to-end timing remains unverified until an equivalent product environment is available.

Reproduction uses the backend frozen environment: decode a one-model source with input/output rates `0.000001`/`0.000002`, normalize once, then time repeated `capture_model_pricing(definition=..., provider=LLMProvider.OPENAI, model_identifier="gpt-test", request_timestamp=aware_now)` calls with `time.perf_counter`; report medians across independent samples.

## Independent Review Corrections

The sole read-only reviewer identified three grounded findings. The root corrected all three and reran invalidated checks:

- R1: active required E2E/support consumers still required removed attempt/generation fields. They now decode `latest_sync`/`usable`, compare current sync start/status facts rather than attempt IDs, and explicitly reject the removed legacy fixture contract.
- R2: a new conversation selector accidentally required an enabled integration. The existing exact/selectable/Workspace save predicate is restored; image/runtime/publication checks remain separate. Credential-stale and disabled conversation selection, plus a disabled conversation with no image tool, have regression coverage.
- R3: nested current diagnostics retained the old adapter's hash-shaped producer version. Current metadata removes only `sha256:` tags containing an actual 64-hex-digit digest; genuine release/schema metadata and immutable history remain intact. Migration fixtures now contain that real legacy shape at top-level and nested positions.

After corrections, root backend tests passed 9,127 cases/3 skipped, the separate migration suite passed 20, the final exact current-data migration regression passed 22, and E2E support passed 555. The same sole reviewer accepted the targeted R1-R3 re-review with no remaining grounded findings; the integrated code review is cleared.

## Local Product E2E Prerequisite Failure

Session environment preparation failed during source readiness, before cloning application data. The current main source requires `minio/mc:latest@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727`; Docker returned `pull access denied for minio/mc` on preparation and direct retry. That exact image was absent from the daemon cache.

No stale image substitution, source reset, revision stamping, database initialization, or bypass was used. The source services started by preparation were stopped with data preserved. The failed Session preparation metadata is retained for diagnosis.

Therefore local assembled API/browser/Runtime E2E, Runtime file/Shell checks, and stop/restart data-preservation QA are **not verified**. Required product E2E must be evaluated by the PR CI. Snapshot implementation dates and temporary-plan cleanup must wait for completion of the remaining validation rather than treat this prerequisite failure as a pass.

## PR CI Corrections

PR #2090's initial commit `aa7a87c84` exposed two additional integration gaps:

- A valid OpenAI-only source failed with HTTP 500 because aggregate preprojection
  treated absent unrelated providers as a global source failure. Expected
  provider-local projection failures now preserve that provider's successful
  current rows, prices, counts, and last-success time; source data, successful
  provider replacements, and failed-provider current status commit in the same
  fenced transaction. Summaries use each provider's actual status/failure facts.
  Global validation/reduction/unexpected-write failures retain the existing
  rollback boundary. This is a scoped-failure restoration within M1/M2/M9, not an
  empty-success reinterpretation or new operational mode.
- The root testenv package still passed a discarded ModelConfig extra field and
  called removed ModelConfig APIs. The actual seed/setup path now uses explicit
  canonical model options for the exact current integration/model identifier,
  without inheriting unrelated Workspace defaults or supplying pricing authority.
  Eleven regressions cover the corrected current seed contract and asynchronous
  initial publication readiness.

The targeted review accepted the backend scoped-failure boundary and identified
one remaining seed readiness race: integration POST completion precedes its
background catalog publication. Deterministic fixture preparation now waits for
integration scope, terminal successful sync, and actual entries. Initial 404,
system fallback, queued, and running observations are polled within a monotonic
deadline; terminal failure, successful-empty, and unexpected API failures propagate
without fallback. Production stale-selection predicates are unchanged.

Root backend Ruff/format/typing and the complete 9,130 passed/3 skipped matrix
passed, including single-provider initial publication, retained failed-provider
data, truthful explicit failure/recovery, and unexpected-write rollback
regressions. Root testenv Ruff/format/typing and 142 tests passed; E2E
Ruff/format/typing and 555 support tests passed. The same sole reviewer accepted
the backend correction and the seed-readiness re-review with no remaining
findings; an independent 11-case seed regression run also passed. No required CI
failure is treated as a pass.

## Decimal Wire Contract Correction

The next CI run at `df5f23d26` reached the corrected source path and exposed a
generated-client pricing decoder failure: the backend legitimately emits a
lossless rate such as `1E-7`, but the inferred Decimal schema pattern omitted
scientific notation. The normalized-rate schema now advertises the actual
decimal-string representation, including exponents and null, without a float
conversion, expanded fixed-point representation, changed raw-source validation,
or pricing-algorithm change. Public/admin clients were regenerated through the
standard workflow; no generated file was manually edited.

Root validation: backend 9,142 passed/3 skipped; testenv 148 passed, including six
actual backend-to-generated-SDK pricing round trips; E2E support 555 passed; fresh
cache-bypassed workspace TypeScript type/lint/format and both product builds
passed. Twelve core cases verify wire/schema agreement in validation and
serialization modes. The same sole reviewer accepted the targeted correction
with no remaining findings and independently executed all six SDK and twelve
core schema cases. Prior review acceptances remain intact.

## Product CI and Snapshot Completion

Implementation commit `917dbe912` passed the complete
[PR CI run](https://github.com/azents/azents/actions/runs/37142158723): all four
required product E2E lanes, web E2E, backend, migration, testenv, TypeScript,
pre-commit, and analysis gates completed without failure. The lane-3 JUnit
artifact explicitly records the saved-support/embedded-price catalog-refresh
test as passed, not skipped (12.890 seconds).

Requirements and Design are marked implemented on 2026-10-04 (KST), current Spec
verification dates are refreshed, and the two temporary implementation plans are
removed in the same feature PR. The final documentation-only commit still
receives its own CI check; implementation evidence above remains tied to its
verified SHA.

No production migration, merge, or deployment is performed. The local environment
prerequisite failure and unverified local stop/restart QA remain explicitly
separate from the successful credential-free product CI evidence.
