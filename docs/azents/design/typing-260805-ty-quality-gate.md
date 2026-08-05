---
title: "Unified Python Type Quality Gate Design"
created: 2026-08-05
updated: 2026-08-05
implemented: 2026-08-05
tags: [python, typing, ci, developer-experience]
document_role: primary
document_type: design
snapshot_id: typing-260805
---

# Unified Python Type Quality Gate Design

- Snapshot: `typing-260805`
- Requirements: [typing-260805/REQ](../requirements/typing-260805-ty-quality-gate.md)
- ADR: [typing-260805/ADR](../adr/typing-260805-ty-quality-gate.md)

## Scope and Ownership

This design changes development quality tooling only. Application runtime behavior, public contracts, persistence, and data-migration semantics remain unchanged.

## Architecture

### M1. Remove active Pyright project ownership

**Authority:** typing-260805/REQ-2, typing-260805/ADR-D1<br>
**Classification:** decided

Remove the backend application's Pyright development dependency and `[tool.pyright]` configuration. Regenerate affected uv lockfiles so the resolved dependency graph no longer includes the direct Pyright package.

### M2. Use a uniform CI and pre-commit `ty` command

**Authority:** typing-260805/REQ-1, typing-260805/ADR-D1<br>
**Classification:** decided

Replace the backend application CI matrix's Pyright selector and conditional step with the existing `ty` command used by the other maintained Python projects. Replace the local Pyright pre-commit hook with a backend `ty` hook and update the structural-hook skip list accordingly.

### M3. Remove active contributor and source-level Pyright ownership

**Authority:** typing-260805/REQ-2, typing-260805/ADR-D1<br>
**Classification:** decided

Update current contributor instructions and reusable type-safety conventions to name `ty`. Remove Pyright directives from maintained non-migration Python source and tests. Preserve existing `ty` suppressions where they remain necessary. Rephrase non-directive comments that describe type-checker behavior without retaining Pyright as the active tool.

### M4. Preserve independent gates and immutable files

**Authority:** typing-260805/REQ-3, typing-260805/ADR-D2<br>
**Classification:** decided

Leave Ruff, pytest, OpenAPI drift, executed Alembic migrations, and implemented historical documents unchanged. Executed migration files are excluded from the directive cleanup even though their inactive historical Pyright comments remain searchable.

## Removal and Replacement

| Removed item | Authority | Replacement / remaining authority | Absence verification |
| --- | --- | --- | --- |
| Backend Pyright dependency and configuration | M1 | `ty` project configuration | Project dependency/config search and lockfile inspection |
| Pyright CI and pre-commit paths | M2 | `ty check --error-on-warning` | Workflow and pre-commit inspection; pre-commit run |
| Current Pyright contributor instructions and directives | M3 | `ty` instructions/directives where needed | Scoped repository search excluding immutable history/migrations |
| Ruff, pytest, OpenAPI gates | M4 | Unchanged | CI/pre-commit configuration and validation results |

## Failure and Recovery

A removed directive cannot alter runtime behavior because it is checker-only metadata. If `ty` reports a diagnostic after the migration, correct the typed code, stub, or narrowly scoped `ty` suppression according to the type-safety convention; do not restore Pyright.

## Test Strategy

This is developer-tooling work with no product behavior change, so an E2E product scenario is not applicable. The primary evidence is the same local quality gate CI executes:

1. Run `uv run ty check --error-on-warning` for the backend application and all maintained Python projects.
2. Run Ruff checks/format checks and relevant pytest suites to prove independent gates remain intact.
3. Run pre-commit on the complete change so generated documentation/convention surfaces and hook wiring are validated.
4. Verify CI runs the uniform `ty` matrix step without a Pyright branch.

No testenv fixture, seed, credential, or live-service prerequisite changes are required.

## Design Authority

- Revision: 1
- Material mechanisms: M1, M2, M3, M4
- Authority set: typing-260805/REQ-1, typing-260805/REQ-2, typing-260805/REQ-3, typing-260805/ADR-D1, typing-260805/ADR-D2

## Feasibility

**Feasible.** The backend application's existing `uv run ty check --error-on-warning` already completes with zero diagnostics, and all other maintained Python CI matrix entries already use that command. The remaining work is configuration, dependency, directive, and documentation migration with no runtime contract change.

## Design Approval

- Mode: collaborative
- Decision owner: requester
- Date: 2026-08-05
- Approved revision: 1
- Approved authority set: typing-260805/REQ-1, typing-260805/REQ-2, typing-260805/REQ-3, typing-260805/ADR-D1, typing-260805/ADR-D2
- Material scope: Pyright removal and `ty` ownership across backend CI, pre-commit, active project configuration, contributor instructions, and maintained non-migration source directives.
- Approval evidence: the requester explicitly instructed implementation and creation of this stacked PR after directing the replacement checker and scope.
