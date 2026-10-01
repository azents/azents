---
title: "Runtime-Aligned Model Metadata Implementation Plan"
created: 2026-10-01
tags: [model-catalog, implementation, backend, engine, migration]
---

# Runtime-Aligned Model Metadata Implementation Plan

## Approved baseline

- Confirmed [Requirements](../requirements/catalog-261001-runtime-aligned-model-metadata.md): `catalog-261001/REQ-1` through `REQ-8`.
- Accepted [ADR](../adr/catalog-261001-runtime-aligned-model-metadata.md): `catalog-261001/ADR-D1` through `ADR-D4`.
- Approved [Design](../design/catalog-261001-runtime-aligned-model-metadata.md): revision 2, exact authority `M1` through `M12`, requester approval on 2026-10-01.
- Implementation requested on 2026-10-01 after refreshing from `origin/main` `aff07a204de44bf72ff3adb11e4d5bedd61459d2`.
- Design delta: `None`.
- Root owns implementation, integration, validation, corrective work, PR publication, stack maintenance, and CI follow-through.
- Exact single independent reviewer: `/root/catalog-metadata-reviewer`, read-only and reused for every stable integrated phase diff.
- PR merge and live deployment remain unauthorized without separate explicit requester instruction.

## Delivery phases

Use three sequential stacked PRs. Open each phase PR before beginning the next phase, create the complete stack before waiting on external CI, and preserve phase branches until the stack is resolved.

| Phase | PR deliverable | Mechanisms | Dependency | Owner |
| --- | --- | --- | --- | --- |
| 1. Source and profile foundation | Direct genai-prices dependency, canonical source adapter and generic source persistence, shared runtime profile resolver, projection provenance and pinned rollback schema, and scheduler-owned shadow preparation without changing current authority | M1-M4, M6, M12; partial M2/M3/M9 | Approved baseline | `/root` |
| 2. Authority cutover and reprojection | Generic source becomes runtime context/pricing authority; system catalogs publish replacement candidates while pinning pre-cutover snapshots; integration sync and bounded network-free reprojection use the replacement resolver/source | M5, M7-M9, M11-M12 plus integrated M1-M6 | Phase 1 PR and stable interfaces | `/root` |
| 3. Cleanup, validation, and spec promotion | Remove active LiteLLM schema/code/config/diagnostics/fixtures, clear rollback pins only after gates, complete migrations and absence checks, run required E2E and quality verification, promote Specs, mark the snapshot implemented, and remove feature plans | M10 plus complete M1-M12 | Phase 2 PR and cutover evidence | `/root` |

## Fixed implementation interfaces

- `RuntimeModelProfileResolver` is the only execution-capability resolver used by catalog projection and runtime model construction. It accepts semantic provider, exact model ID, optional publisher/family/listing evidence, optional source record, and optional Bedrock assembly metadata.
- The resolver returns runtime route/model kind, effective partial profile, normalized capabilities, execution options, projectability, source match, and deterministic revision evidence. Raw `ModelProfile` objects are not persisted.
- `GenAIPricesSourceAdapter` uses public `UpdatePrices.fetch()` only, never the global updater or private parser. The trusted operator URL and timeout are its transport boundary; the public operation buffers the full response.
- Generic source persistence uses an explicit authority row plus immutable content-addressed snapshots. Catalog cutover uses one `rollback_snapshot_id` pin per catalog and ordinary publication cannot delete the pinned snapshot.
- Operation-local context and pricing capture one durable snapshot. Provider-reported charges remain separate and take precedence.
- Provider listing remains integration visibility authority. Cutover reprojection may use stored current entries without making provider calls.
- Migrations are generated with Alembic from the current linear head. Existing executed revisions are immutable.
- Public/generated clients are regenerated only when authoritative schema changes require them.

## Validation matrix

Each phase runs focused Ruff, format check, configured `ty`, focused pytest, documentation validation, and independent review. Database phases use isolated PostgreSQL migration/repository tests. Phase 3 additionally runs whole backend checks, deterministic source/profile/pricing parity, fresh and seeded upgrade migrations, required model-selection/Admin/context/pricing/saved-selection E2E, testenv quality, generated-client checks when affected, spec review, and active LiteLLM absence checks.

Authenticated live-provider checks are optional diagnostics. Missing credentials skip them explicitly and never replace deterministic evidence. No live Kubernetes or production database operation belongs to this work.

## Removal ownership

- Phase 1 removes duplicated inline runtime profile construction only after the shared resolver owns identical behavior. Legacy catalog/source authority remains active.
- Phase 2 removes active reads/publication from the legacy source and replaces context, pricing, system projection, integration projection, and enrichment consumers. Legacy storage remains only for explicit coordinated rollback.
- Phase 3 removes every remaining active LiteLLM table, constraint, field, source key, environment variable, type, loader/service/repository, decoder, failure code, scheduler description, diagnostic, fixture, and current persisted metadata key. Historical documents and executed migrations remain factual.

## Rollout and rollback

- Phase 1 is shadow-only. Current pointers/readers do not change and rollback is ordinary.
- Phase 2 requires current replacement source and complete system candidates. Cutover publication pins each exact pre-cutover current snapshot, switches current to the replacement, and keeps the pin through the reprojection window. Coordinated rollback uses the pin; runtime never falls back automatically.
- Phase 3 drops legacy state and pinned snapshots only after backup, replacement provenance, absence, and validation gates. Post-cleanup rollback requires the matching pre-cleanup database backup and previous release.
- The implementation produces code and migration artifacts only; no live cutover is executed.

## Review and drift control

For each phase, root completes implementation and integrated validation, freezes the diff, and asks `/root/catalog-metadata-reviewer` for one read-only review. Root applies findings and requests targeted re-review only for requirement/design, security/data-loss, material convention, or interface corrections.

At every checkpoint verify both directions: assigned mechanisms/removals are present, and no source of truth, fallback, compatibility mode, API contract, failure mode, or operational authority exists outside `M1`-`M12`. Material drift returns to feature design. Local file layout, helper boundaries, cache sizing, and equivalent fixture composition remain root-owned details.

## Spec and plan lifecycle

Update reachable Specs in the owning phase. Perform final spec review after complete validation. Add the same `implemented` date to Requirements and Design only after required verification passes. Remove this plan and all phase plans in phase 3 after spec promotion and before the final PR is frozen.

Current checkpoint: revision 2 is approved and independently reviewed, current main is integrated, the exact reviewer is assigned, and phase 1 planning is active.

Design delta: `None`.
