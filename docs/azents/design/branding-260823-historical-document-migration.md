---
title: "Historical Document Branding Migration Design"
created: 2026-08-23
updated: 2026-08-23
implemented: 2026-08-23
tags: [branding, documentation, migration]
document_role: primary
document_type: design
snapshot_id: branding-260823
---

# Historical Document Branding Migration Design

- Snapshot: `branding-260823`
- Document reference: `branding-260823/DESIGN`
- Requirements: [branding-260823/REQ](../requirements/branding-260823-historical-document-migration.md)
- Decisions: [branding-260823/ADR](../adr/branding-260823-historical-document-migration.md)

## Current Behavior and Gaps

Current code and mutable documentation use Azents naming, but immutable historical
snapshots, exact provenance records, generated index entries, and nine tracked paths
still expose the superseded brand. The ordinary immutability policy blocks direct
editing without the bounded exception in `branding-260823/ADR-D1`.

## Migration Design

### Content migration

Apply canonical replacements to every tracked text file, including historical
Requirements, ADRs, Designs, provenance records, and generated documentation
surfaces. Preserve capitalization and established Azents naming contracts:

- product prose uses `Azents`;
- code, package, command, and resource identifiers use `azents`;
- environment-variable prefixes use `AZ_`;
- product and API URLs use the `azents.io` domain; and
- TypeScript packages use the canonical `@azents/*` namespace.

### Canonical path and ID migration

Rename each historical snapshot path containing the superseded brand. Apply the
same basename to its Requirements, ADR, and Design trio where applicable. Replace
snapshot IDs, migration-source values, relative links, and repository references
atomically.

### Provenance

Remove superseded literals from tracked provenance records. The parent Git commit
and `branding-260823` snapshot provide the before/after audit trail required by
`branding-260823/ADR-D3`.

### Documentation policy

Update root and documentation-scoped `AGENTS.md` guidance to identify
`branding-260823` as a completed one-time exception. The general lifecycle remains
unchanged after migration.

## Failure, Rollback, and Recovery

- Perform the migration in one focused pull request and one reviewable commit series.
- If validation fails, correct references or revert the migration commit before
  merge; do not add compatibility aliases.
- The parent commit is the rollback and literal-provenance boundary.
- No runtime state, database migration, or external service mutation is involved.

## Test Strategy

### Primary verification

1. Scan all tracked text content case-insensitively for the superseded brand and
   require zero matches.
2. Scan all tracked paths and require zero matches.
3. Regenerate documentation indexes and run all snapshot validation tests.
4. Validate that renamed snapshot trios share matching basenames and that tracked
   relative links resolve.
5. Run the applicable Python, testenv, and changed-file pre-commit checks.

### Fixtures and prerequisites

No E2E fixture or external credential is required because the migration changes
repository documentation, one display-name default, and test identifiers without
changing a user interaction flow.

### Evidence

The pull request records scan counts, renamed paths, validation commands, and CI
results. Any skipped check must include a concrete reason.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | One brand-only rewrite of otherwise immutable historical documents | `branding-260823/ADR-D1`, `branding-260823/REQ-1`, `REQ-3`, `REQ-4` | `decided` |
| M2 | Atomic filename, snapshot ID, reference, and index migration without aliases | `branding-260823/ADR-D2`, `branding-260823/REQ-1`, `REQ-2` | `decided` |
| M3 | Git history and this snapshot retain literal provenance | `branding-260823/ADR-D3`, `branding-260823/REQ-3` | `decided` |
| M4 | Zero-match scans and repository validators gate completion | `branding-260823/REQ-1`, `REQ-2`, `REQ-5` | `required` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Superseded brand literals in tracked content | `branding-260823/ADR-D1` | Canonical Azents naming | All tracked text files | Zero-match content scan |
| Superseded canonical document paths and IDs | `branding-260823/ADR-D2` | Canonical Azents paths and IDs | Nine tracked paths plus all references | Zero-match path scan and snapshot validation |
| Literal provenance retained in the tracked tree | `branding-260823/ADR-D3` | Parent Git commit and migration snapshot | Provenance JSON and historical metadata | Zero-match scan and Git diff review |
| General permission to rewrite implemented snapshots | `branding-260823/REQ-4` | Normal immutability policy | Ends after verified migration | AGENTS guidance and implemented snapshot marker |

## Feasibility

- Content and path migration is repository-local and mechanically enumerable:
  feasible.
- Snapshot basenames and cross-references can be validated by existing documentation
  tooling: feasible.
- Exact prior literals remain recoverable from Git history: feasible.
- External deep-link redirects are outside this repository and remain a non-blocking
  operational follow-up.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `건우`
- Approved on: `2026-08-23`
- Approved Design revision: `1`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`
- Approved scope: One-time complete migration of historical documentation content,
  canonical identifiers, provenance records, and generated indexes to Azents naming.
