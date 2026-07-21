---
title: "Shared Development Snapshot Identifier Design"
created: 2026-07-21
updated: 2026-07-21
implemented: 2026-07-21
tags: [documentation, process, architecture, testing]
document_role: primary
document_type: design
snapshot_id: docids-260721
migration_source: "docs/azents/design/docids-260721-shared-development-snapshot-identifiers.md"
---

# Shared Development Snapshot Identifier Design

- Snapshot: `docids-260721`
- Document reference: `docids-260721/DESIGN`
- Requirements: [Shared Development Snapshot Identifier Requirements](../requirements/docids-260721-shared-development-snapshot-identifiers.md) (`docids-260721/REQ`)
- ADR: [Shared Development Snapshot Identifiers](../adr/docids-260721-shared-development-snapshot-identifiers.md) (`docids-260721/ADR`)

## Overview

This design replaces global ADR-number allocation for newly created development snapshots with one shared dated identifier and basename across Requirements, ADR, and Design. It updates the documentation policy, feature-design and feature-shipping workflows, deterministic validation, and validation tests while leaving existing historical documents untouched.

## Current State and Gaps

- Requirements already use `{word}-{YYMMDD}-{slug}.md` and expose `{word}-{YYMMDD}` as a short ID.
- ADR guidance still requires the next repository-wide `NNNN` identifier.
- Design guidance uses descriptive filenames unrelated to the Requirements snapshot.
- The documentation validator checks only Requirements naming, date consistency, and short-ID uniqueness.
- Existing ADR number collisions demonstrate that a global sequence is not safe under parallel branch creation.

## Traceability

| Requirement | ADR decisions | Design mechanism |
| --- | --- | --- |
| `docids-260721/REQ-1` | `docids-260721/ADR-D1` | Canonical snapshot parser derives `{word}-{YYMMDD}` from the common filename pattern. |
| `docids-260721/REQ-2` | `docids-260721/ADR-D2`, `docids-260721/ADR-D3`, `docids-260721/ADR-D5` | Policy, skills, and validation use one basename and progressive trio states. |
| `docids-260721/REQ-3` | `docids-260721/ADR-D4` | Documentation rules and skills define snapshot-first typed references. |
| `docids-260721/REQ-4` | `docids-260721/ADR-D1`, `docids-260721/ADR-D3`, `docids-260721/ADR-D5` | Validation detects duplicate short IDs and mismatched sibling basenames without global allocation. |
| `docids-260721/REQ-5` | `docids-260721/ADR-D6` | Legacy ADR and Design names bypass new-format validation and remain unchanged. |
| `docids-260721/REQ-6` | `docids-260721/ADR-D7` | Lifecycle guidance freezes the trio after verified implementation and keeps current behavior in Specs. |

## Artifact Model

### Canonical filename

The canonical new core-document filename is:

```text
{word}-{YYMMDD}-{slug}.md
```

The same basename is used at:

```text
docs/azents/requirements/{basename}
docs/azents/adr/{basename}
docs/azents/design/{basename}
```

`{word}-{YYMMDD}` is the snapshot identifier. `{slug}` improves discovery but is not part of the short ID.

### Core documents and non-core records

The shared basename applies only to the Requirements, ADR, and primary Design for a development snapshot. Specs remain living current-state documents. Notes, Issues, Plans, audit reports, validation reports, and other supporting records retain their existing naming conventions.

### Typed references

Writers use:

```text
<snapshot>
<snapshot>/REQ
<snapshot>/REQ-N
<snapshot>/ADR
<snapshot>/ADR-DN
<snapshot>/DESIGN
```

Documents use Markdown links on the first meaningful cross-document mention. Short references are sufficient for repeated references when the target remains clear.

## Lifecycle

The snapshot state is derived from files present on disk:

| State | Requirements | ADR | Design | Valid |
| --- | --- | --- | --- | --- |
| Confirmed intent | Present | Absent | Absent | Yes |
| Decision discussion | Present | Present | Absent | Yes |
| Complete design | Present | Present | Present | Yes |
| ADR without confirmed intent | Absent | Present | Any | No |
| Design before ADR | Present | Absent | Present | No |
| Design without Requirements | Absent | Any | Present | No |

If a new-format Requirements or Design document contains `implemented`, the complete trio must exist. Once implementation is complete and verified, Requirements and Design receive the same implementation date and all three documents become immutable.

## Documentation Policy Changes

`docs/azents/AGENTS.md` becomes the source of truth for:

- the shared filename and typed reference formats;
- one Requirements/ADR/Design document per snapshot;
- progressive lifecycle states;
- legacy compatibility;
- which supporting document classes are excluded; and
- validation behavior.

The repository-root `AGENTS.md` summarizes the common snapshot relationship so agents entering from other project areas do not apply the old ADR-number workflow.

## Workflow Changes

### Feature design

The `feature-design` workflow selects the basename when the Requirements document is created. After confirmation, it creates the ADR and Design at the sibling paths with that exact basename. Accepted hard-to-reverse decisions are appended to the one ADR and referenced as `<snapshot>/ADR-DN`.

### Feature shipping

The `ship-feature` workflow verifies that the approved Requirements, ADR, and Design share one snapshot and basename before implementation planning. Spec promotion marks Requirements and Design implemented only after the shipped behavior is verified.

## Validator Design

### Per-document validation

- Requirements must always match the canonical filename pattern.
- ADR and Design files matching the canonical pattern are treated as new snapshot documents.
- New snapshot documents must be directly under their core directory.
- Every new snapshot document's `created` date must use `YYYY-MM-DD`.
- Only the Requirements `created` date must match the filename date. ADR and Design record their actual creation dates while retaining the shared basename.
- Legacy ADR and Design filenames remain accepted by the existing common-frontmatter rules.

### Cross-document validation

For each snapshot short ID:

1. reject more than one basename in the same core document type;
2. require Requirements before a new-format ADR or Design;
3. require ADR before a new-format Design;
4. require every present core document to match the Requirements basename; and
5. require the full trio when a new-format Requirements or Design is marked implemented; and
6. require Requirements and Design to use the same implementation date.

The validator intentionally allows Requirements-only and Requirements-plus-ADR states so normal feature-design work can be saved and reviewed before the Design exists.

### Index behavior

Requirements remain listed by canonical short ID. ADR index entries continue to include both legacy numbered ADRs and new snapshot ADRs. Design documents remain excluded from the generated index under the existing discovery policy.

## Compatibility and Rollout

- Do not rename or edit existing ADR or Design documents.
- Do not rewrite legacy `ADR-NNNN-DN` references.
- Begin using the shared format for new feature-design snapshots after this policy is merged.
- Defer migration, redirects, or compatibility aliases to a separately approved snapshot.
- Reject invalid new snapshot relationships in pre-commit and CI; no runtime rollout is involved.

## Feasibility

| Requirement | Result | Evidence |
| --- | --- | --- |
| `docids-260721/REQ-1` | Feasible | The existing Requirements parser already extracts `{word}-{YYMMDD}` without a registry. |
| `docids-260721/REQ-2` | Feasible | The validator scans all three directories and can compare basenames by short ID. |
| `docids-260721/REQ-3` | Feasible | References are documentation-level identifiers with no external storage schema. |
| `docids-260721/REQ-4` | Feasible | Deterministic duplicate and mismatch checks run in the existing pre-commit/CI hook. |
| `docids-260721/REQ-5` | Feasible | New validation is activated only for canonical-pattern ADR and Design filenames. |
| `docids-260721/REQ-6` | Feasible | Existing `implemented` frontmatter and immutable-document policy extend to the complete trio. |

No product, API, persistence, security, or runtime blocker exists.

## Test Strategy

This change affects repository documentation policy and deterministic tooling only. It changes no user-facing runtime behavior, so browser, API, or testenv E2E coverage is not applicable.

### Deterministic validation matrix

| Scenario | Expected result |
| --- | --- |
| Requirements only | Pass |
| Requirements plus matching ADR | Pass |
| Complete matching trio | Pass |
| ADR and Design created after the Requirements date | Pass |
| Legacy numbered ADR and descriptive Design | Pass |
| ADR without Requirements | Fail |
| Design without ADR | Fail |
| Same short ID with different basenames | Fail |
| Duplicate short ID in one document type | Fail |
| Implemented snapshot without complete trio | Fail |
| Requirements and Design with missing or different implementation dates | Fail |
| Requirements filename date differing from its `created` date | Fail |

### Fixtures and prerequisites

- Tests create temporary documentation trees inside the repository root and remove them after each case.
- No database, network, credentials, testenv fixture, or external service is required.
- The repository's Python version and standard library are sufficient.

### Evidence and CI policy

- Run the validator unit tests through a dedicated pre-commit hook.
- Run `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`.
- Run `python -m py_compile scripts/gen_docs_index.py`.
- Any invalid fixture accepted, valid fixture rejected, stale generated index, or validator error fails CI.
- Product E2E is intentionally not scheduled rather than skipped conditionally.

## Risks

- Policy alone cannot distinguish a newly created legacy-looking ADR or Design filename from genuine historical content. Agent workflow guidance is the enforcement boundary for choosing the new format; deterministic validation enforces consistency once the canonical format is used.
- Short words may collide on busy dates. The policy requires a more precise word rather than ordinals, preserving readable identifiers.
- The repository remains heterogeneous by design until a future migration is explicitly approved.
