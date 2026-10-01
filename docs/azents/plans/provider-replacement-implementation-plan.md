---
title: "Provider Replacement Implementation Plan"
created: 2026-09-30
tags: [inference, implementation, migration]
---

# Provider Replacement Implementation Plan

## Approved baseline

- Confirmed [Requirements](../requirements/inference-260930-provider-replacement.md): REQ-1 through REQ-8.
- Accepted [ADR](../adr/inference-260930-provider-replacement.md): ADR-D1 through ADR-D5.
- Approved [Design](../design/inference-260930-provider-replacement.md): revision 1; exact mechanisms M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, M11, M12, M13; requester approval on 2026-09-30 (KST).
- Implementation separately requested on 2026-09-30 (KST). Deployment and PR merge are not authorized.
- Design delta: `None`.
- Root owns execution, integration, final validation, review requests, corrective work and all PRs through CI.
- Exact single independent reviewer: `/root/provider-replacement-reviewer` (read-only, reused for every stable integrated phase diff).

## Delivery phases

Use three reviewable sequential PRs. Create each phase PR before beginning the next phase; create the entire series before waiting for external CI. These branches are development decomposition, not a permanent dual-runtime product mode. The coordinated schema/dependency/provider cutover in phase 3 is the release boundary.

| Phase | PR deliverable | Mechanisms and authority | Dependencies | Owner |
| --- | --- | --- | --- | --- |
| 1: retained-source ingestion | Remove executable LiteLLM schema/URL/version/bundled accesses from catalog ingestion, preserve source authority and projection behavior, fix same-hash historical provenance and prove package-free ingestion | M7, M12, M13; REQ-1/6/7/8; ADR-D1/D5 | Approved baseline | Root integration; assigned source implementer |
| 2: context and usage/pricing | Validated-source context lookup across all callers; normalized snapshot-backed pricing/usage provenance and native OpenAI cost replacement; golden rules and generated API contracts if changed | M8, M9, M12, M13; REQ-1/6/7/8; ADR-D1/D2/D5 | Phase 1 PR exists and interfaces stable | Root and bounded assigned implementation workstreams |
| 3: complete provider and semantic catalog cutover | Pydantic model interaction, observation/public extension, exact native history/terminal/tool/credential behavior; target-free schema/API/client transition; dependency/old-runtime removal; full deterministic E2E, Specs and plan cleanup | M1-M6, M10-M13 plus integrated M7-M9; REQ-1 through REQ-8; ADR-D1 through ADR-D5 | Phase 2 PR exists and context/pricing interfaces stable | Root and bounded non-overlapping workstreams |

## Interfaces and ownership

- Canonical history, lifecycle, tool execution, retries and integration authorization remain existing Azents-owned contracts.
- Retained-source parsing is owned by phase 1, returns validated source metadata and aliases with existing JSON snapshot persistence. It creates no alternate data authority.
- Phase 2 pricing receives one validated snapshot and normalized usage/billing metadata; it does not read output content or fetch a source. Context helpers receive explicit local source metadata, not a runtime-prefix inference heuristic.
- Phase 3 SDK/model construction receives semantic provider/raw ID and resolved secret-bearing integration view; native observation is dispatch-local and not a transcript owner.
- API contracts are regenerated from authoritative schemas; never hand-edit generated clients. New migrations come from `alembic revision`, never edits to executed revisions.
- Individual phase plans assign exact non-overlapping file ownership before implementation. Root owns shared definitions, integration, validation, code review requests, commits and PR publication.

## Verification and prerequisites

Each phase runs focused Ruff, configured type checking and tests, root-owned integrated checks, then independent review of a stable diff. Required deterministic E2E, fresh/upgrade migrations, generated-client consistency and package-free import/dependency absence run before final sign-off. Full E2E matrices, seeds and evidence requirements are in Design Test Strategy.

Local test containers and Session-scoped development environments may be used; never mutate live cluster resources. Main/other Session credentials, data and environment files are not displayed or repurposed as disposable fixtures. Record safe prerequisite identity, dependency/fixture versions, command/result and evidence limits.

Authenticated provider checks are separate from source/unit/deterministic E2E. Missing prerequisites yield explicit optional-test skips, not provider parity claims; release for an unverified affected route remains conditional. Do not remove routes or change endpoints to bypass failures.

## Removal mapping

- Phase 1: package-provided source schema, installed URL/version lookup and bundled fallback. Retain dataset keys/table names/historical payloads, last-good/fencing and exact alias/capability semantics.
- Phase 2: `get_model_info`, process-local `model_cost`, `completion_cost` and obsolete pricing response helper. Preserve fallback math, null prices and separately reported charges.
- Phase 3: executable transport/exception imports, runtime-prefix and credential kwargs, active catalog target/runtime columns and exact JSON keys, obsolete enum/index dimensions, old execution fixtures and maintenance configuration. Re-own behavior assertions before removal.
- Historical source/snapshot/attempt/native IDs and FKs, saved semantic selections, independent OpenAI/image executors, executed migrations and implemented documents are retained.
- Classify `litellm` search matches: retained data/historical names are legitimate; imports, dependency edges and obsolete active dispatch are not.

## Specs, rollout and cleanup

Update Specs in the phase where behavior becomes reachable; perform final spec review for integrated implemented behavior. Do not set Requirements/Design `implemented` until implementation and required validation pass. Phase 3 must drain incompatible writers and requires coordinated compatible schema/backend/generated client release; no actual deployment is performed by this implementation task.

After final validated spec promotion, remove this plan and phase plans in the final feature cleanup work, without adding a standalone PR solely for workflow ceremony. PRs are not merged without explicit user approval.

## Checkpoints and drift control

At every phase boundary record base/branch/PR, completed mechanisms, changed interfaces, validation and reviewer result, removals/absence evidence, remaining risks and next phase. Check approved work missing and unapproved behavior added. Findings within an approved contract are implementation work; material authority changes require Design revision/approval before the affected lane proceeds.

Current checkpoint: approved revision recorded; phase 1 planning and implementation starting. No application or deployment change was present at baseline.
