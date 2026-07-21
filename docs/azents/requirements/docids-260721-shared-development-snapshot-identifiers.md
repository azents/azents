---
title: "Shared Development Snapshot Identifier Requirements"
created: 2026-07-21
updated: 2026-07-21
implemented: 2026-07-21
tags: [documentation, process, architecture]
---

# Shared Development Snapshot Identifier Requirements

- Snapshot: `docids-260721`
- Document reference: `docids-260721/REQ`

## Problem

Globally incremented ADR numbers require parallel branches to reserve identifiers or resolve filename and reference conflicts during rebase. Requirements, ADR, and Design documents for the same development effort also use unrelated names, which makes the complete historical context difficult to discover.

## Primary Actor

A developer or agent creating Requirements, ADR, and Design documents on a parallel feature branch.

## Primary Scenario

Two independent development efforts create their core documents concurrently without coordinating a global number. Each effort chooses its own `{word}-{YYMMDD}` snapshot identifier, uses one shared basename for its Requirements, ADR, and Design documents, and later rebases and merges without identifier conflicts.

## Supporting Scenarios

- A reviewer locates the Requirements, ADR, and Design for one development effort from any one of the three documents.
- A reader follows typed references to the whole snapshot, an individual requirement, an ADR decision, or the Design document.
- Existing numbered ADRs, existing Design filenames, and legacy references remain readable without migration.

## Goals

- Remove global ADR-number allocation from new development-document creation.
- Make related Requirements, ADR, and Design documents discoverable through one shared identifier and basename.
- Provide stable, unambiguous references for snapshot documents and their local items.
- Preserve existing historical documents and references.

## Non-Goals

- Migrate or rename existing ADR or Design documents.
- Change Spec filenames or references.
- Change Notes, Issues, or Plans naming.
- Change audit or validation report naming.
- Rewrite existing ADR content or decision structures.

## Requirements

### REQ-1. Shared development snapshot identifier

One feature-design effort must use a shared snapshot identifier in the form `{word}-{YYMMDD}`.

**Acceptance criteria**

- `{word}` is a short, precise, lowercase feature word.
- `{YYMMDD}` is the KST creation date of the snapshot.
- The snapshot identifier does not depend on a global sequence or registry.

### REQ-2. Consistent core-document basename

Requirements, ADR, and Design documents for one snapshot must use the same `{word}-{YYMMDD}-{slug}.md` basename in their respective directories.

**Acceptance criteria**

- The related files are placed under `requirements/`, `adr/`, and `design/`.
- All three files have an identical basename.
- Each snapshot has at most one Requirements, one ADR, and one Design document.
- Multiple hard-to-reverse decisions for the snapshot are recorded in the one ADR document.

### REQ-3. Stable typed references

The documentation system must support typed short references for the snapshot, its documents, requirements, and ADR decisions.

**Acceptance criteria**

- `<snapshot>` identifies the complete development snapshot.
- `<snapshot>/REQ` identifies its Requirements document.
- `<snapshot>/REQ-N` identifies an individual requirement.
- `<snapshot>/ADR` identifies its ADR document.
- `<snapshot>/ADR-DN` identifies an individual ADR decision.
- `<snapshot>/DESIGN` identifies its Design document.

### REQ-4. Conflict-free parallel creation

New core-document creation must not require global identifier reservation, and duplicate snapshot identifiers must be detected in validation.

**Acceptance criteria**

- Independent efforts with different snapshot identifiers can be created and rebased without renumbering.
- Reusing one snapshot identifier for different basenames in the same document type fails validation.
- A same-word, same-date collision is resolved by combining the same effort or choosing a more precise word.
- Arbitrary numeric suffixes are not used to resolve a collision.

### REQ-5. Preserve existing documents

Existing numbered ADR filenames, existing Design filenames, and legacy `ADR-NNNN-DN` references must remain unchanged and supported.

**Acceptance criteria**

- Existing ADR and Design files pass documentation validation without renaming.
- New creation guidance uses the shared snapshot format.
- Existing document migration is deferred to a separate future effort.

### REQ-6. Immutable implemented snapshots

After implementation is complete and verified, the Requirements, ADR, and Design documents form an immutable historical snapshot.

**Acceptance criteria**

- Later work on the same topic creates a new snapshot identifier and new core documents.
- Implemented snapshot documents are not rewritten to describe later behavior.
- Living Specs remain the only documentation layer that represents current behavior.

## Fixed Constraints

- Snapshot dates use KST.
- The slug names the specific development capability rather than an implementation technique or broad topic.
- Requirements, ADR, and Design use the same basename.
- Existing documents and references remain readable.
- Only newly created core development documents use the new format.

## Open Assumptions

- None.

## Success Criteria

At least two parallel branches can create different core-document snapshots without number coordination and merge after rebase without filename, short-ID, or decision-reference conflicts.

## Confirmation

Confirmed by the requester on 2026-07-21 before the ADR and Design decisions were recorded.
