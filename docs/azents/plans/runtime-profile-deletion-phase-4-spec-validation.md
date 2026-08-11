---
title: "Runtime Profile Deletion Phase 4 Validation and Living Spec Promotion"
created: 2026-08-11
updated: 2026-08-11
tags: [runtime, profile, validation, spec, e2e]
---
## Phase Execution Plan

- Phase: `4 - Integrated validation and Living Spec promotion` (stack PR `5/6`)
- Branch/base: `feature/runtime-profile-deletion-spec-validation` → `feature/runtime-profile-deletion-web`
- PR boundary: Validate the cumulative Runtime configuration current-state and Runtime Profile hard-delete implementation, update current Living Specs to the proven behavior, and mark the approved Requirements and Design implemented on 2026-08-11.
- Inputs: Approved `profile-260811/REQ`, accepted `profile-260811/ADR`, approved `profile-260811/DESIGN` revision 1, implementation PRs 2/6 through 4/6, generated clients, focused Python/TypeScript checks, and the passing Docker-backed owner deletion Web E2E.
- Deliverables: cumulative code/spec traceability and scope-drift evidence; active-source absence evidence for removed configuration-revision authority and deletion substitutes; focused and repository-required validation evidence; current Agent, Workspace, Runtime Provider, Runtime Control, Runtime Persistence, Toolkit, and Agent Execution Living Specs describing bounded desired/applied current state and owner hard deletion; matching `implemented: 2026-08-11` metadata on Requirements and Design.
- Non-goals: New product behavior, new API or protocol mechanisms, compatibility or fallback paths, migration edits, live deployment or Kubernetes writes, PR merges, implementation-plan cleanup, or rewriting the accepted ADR.
- Interfaces: Current configuration authority is Runtime ID plus positive configuration sequence, digest, desired generation, and Provider/Runner generation evidence; deletion remains exact-version Owner-only hard delete with atomic selection clearing, no fallback, retained applied/runtime/workspace state, and bounded impact counts; Specs describe only current behavior.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`
- Authority references: `profile-260811/REQ-1` through `REQ-8`; `profile-260811/ADR-D1` through `ADR-D6`; `profile-260811/DESIGN` revision 1; current documentation and validation conventions.
- Design delta: `None`
- Removal obligations: Remove revision UUID authority, revision table/models/repositories/pointers/receipt fields/protocol terminology/public response models/Web labels from active current-behavior documentation; describe no archive, tombstone, fallback Profile, mixed protocol, or historical configuration catalog.
- Absence verification: Cumulative active-source and current-Spec searches for `runtime_configuration_revisions`, revision repositories/pointers, Runtime Control `revision_id`, public revision response models, raw delete HTTP, archive/tombstone/fallback deletion substitutes, and stale desired/applied revision wording; schema/OpenAPI/generated-client inspection and focused tests remain evidence.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Cumulative validation | `root` | repository validation commands and evidence only | Stable PR 4/6 head | Required Python, migration, protocol, TypeScript, docs, and E2E results | Focused/repository checks, pre-commit, Docker E2E evidence |
| Spec impact and promotion | `root` | `docs/azents/spec/domain/{agent,workspace,runtime-provider,toolkit}.md`, `docs/azents/spec/flow/{agent-runtime-control,agent-runtime-persistence,agent-execution-loop}.md` | Proven cumulative implementation | Current-state and deletion behavior in Living Specs with refreshed verification dates | `/spec-review` reasoning, stale-term searches, docs validation |
| Snapshot implementation metadata | `root` | `docs/azents/requirements/profile-260811-runtime-profile-deletion.md`, `docs/azents/design/profile-260811-runtime-profile-deletion.md` | Required validation passes and Specs match implementation | Matching implementation date | Snapshot validator and docs pre-commit hooks |
| Scope/removal audit | `root` | cumulative diff and active sources | All implementation PRs | Mechanism coverage, unauthorized-mechanism absence, removal evidence | Targeted searches and independent review |

- Integration order: Record this phase plan → map cumulative changed paths to current Specs → update Specs and stale terminology → run focused docs/source checks → run required cumulative validation and E2E evidence → add matching implemented metadata → run final pre-commit → independent review → commit and open PR 5/6.
- Independent review: `hardtack` reviews the stable cumulative validation/spec diff read-only against confirmed Requirements, accepted ADR, approved Design revision 1, implementation PRs, current code, and this plan. Required criteria are complete M1-M8 coverage, accurate current-state and deletion semantics, no immutable ADR rewrite, matching implementation metadata, removal completeness, and no new behavior hidden in Specs.
- Final validation: docs frontmatter/snapshot/index hooks; targeted stale-authority and deletion-substitute searches; affected Python Ruff/format/ty/pytest and migration/protocol generation checks; TypeScript format/lint/typecheck/build; testenv checks; focused Docker Web deletion E2E and available cumulative Runtime Profile/current-state E2E; `git diff --check`; full pre-commit hooks.
- Scope-drift check: Confirm every approved mechanism M1-M8 is implemented and documented; confirm no new state authority, fallback, compatibility, operational mode, deletion permission, API contract, or migration behavior appears; defer plan deletion only to PR 6/6.
- Context checkpoint: PRs 2/6-4/6 replace permanent configuration revisions, add exact Owner hard deletion, and expose the owner Web flow. Focused local checks and the primary Docker Web E2E pass. PR #1260 currently has an external deterministic-E2E failure to diagnose during stack-wide CI work; this phase records/fixes only implementation defects grounded by validation. Remaining work after this PR is plan cleanup, full-stack review corrections, and CI monitoring without merge.
