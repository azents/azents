---
title: "Shared Development Snapshot Identifiers"
created: 2026-07-21
document_role: primary
document_type: adr
snapshot_id: docids-260721
tags: [documentation, process, architecture]
---

# Shared Development Snapshot Identifiers

- Snapshot: `docids-260721`
- Document reference: `docids-260721/ADR`
- Requirements: [Shared Development Snapshot Identifier Requirements](../requirements/docids-260721-shared-development-snapshot-identifiers.md) (`docids-260721/REQ`)

## Status

Accepted.

## Context

New feature-design work produces three historical documents with different responsibilities: Requirements capture confirmed product intent, an ADR captures hard-to-reverse decisions, and a Design describes the implementation approach. The prior naming rules gave Requirements a dated short ID, allocated ADRs from one repository-wide sequence, and allowed unrelated Design filenames.

Parallel branches therefore had to coordinate or repair ADR numbers, and a document name alone could not reliably identify the other documents from the same effort. Existing history cannot be renamed safely because filenames and legacy `ADR-NNNN-DN` references may be linked from code, pull requests, issues, and external records.

## Decisions

### `docids-260721/ADR-D1` — Use a shared dated snapshot identifier

Each new development snapshot uses `{word}-{YYMMDD}` as its canonical identifier.

- `{word}` is a short, precise, lowercase feature word.
- `{YYMMDD}` is the KST date on which the Requirements snapshot is created. The ADR and Design keep this filename date if they are created later, while their `created` frontmatter records their actual creation dates.
- The identifier is allocated locally by the development effort, without a global registry or sequence.
- A same-word, same-date collision is resolved by combining the same effort or selecting a more precise word, never by adding an arbitrary ordinal.

This decision satisfies `docids-260721/REQ-1` and `docids-260721/REQ-4`.

### `docids-260721/ADR-D2` — Share one basename across the core documents

The new Requirements, ADR, and Design files use the identical `{word}-{YYMMDD}-{slug}.md` basename under their respective directories.

```text
requirements/slack-260721-channel-agent-conversation.md
adr/slack-260721-channel-agent-conversation.md
design/slack-260721-channel-agent-conversation.md
```

The slug identifies the specific development capability. It is not a version marker or implementation name.

This decision satisfies `docids-260721/REQ-2`.

### `docids-260721/ADR-D3` — Keep one document of each core type per snapshot

One snapshot contains at most one Requirements document, one ADR, and one Design. The ADR contains all hard-to-reverse decisions for that snapshot as local `D1`, `D2`, and subsequent decision entries instead of allocating a separate globally numbered ADR for each decision.

This decision satisfies `docids-260721/REQ-2` and `docids-260721/REQ-4`.

### `docids-260721/ADR-D4` — Use snapshot-first typed references

References use the shared snapshot identifier first and add a document or local-item suffix:

| Reference | Target |
| --- | --- |
| `<snapshot>` | Complete development snapshot |
| `<snapshot>/REQ` | Requirements document |
| `<snapshot>/REQ-N` | Individual requirement |
| `<snapshot>/ADR` | ADR document |
| `<snapshot>/ADR-DN` | Individual ADR decision |
| `<snapshot>/DESIGN` | Design document |

The first meaningful mention should link to the target document. Later mentions may use the short reference alone.

This decision satisfies `docids-260721/REQ-3`.

### `docids-260721/ADR-D5` — Validate progressive snapshot construction

The feature-design lifecycle creates documents in this order:

```text
Requirements → ADR → Design
```

Validation therefore permits these states:

1. Requirements only;
2. Requirements and ADR; or
3. Requirements, ADR, and Design.

An ADR or Design cannot introduce a new-format snapshot without its Requirements, and a Design cannot precede its ADR. Any new-format documents that coexist must use the same basename. A snapshot marked implemented must contain the complete trio.

This decision satisfies `docids-260721/REQ-2` and `docids-260721/REQ-4`.

### `docids-260721/ADR-D6` — Preserve legacy history without migration

Existing numbered ADRs, existing Design filenames, and legacy references remain valid and unchanged. The shared snapshot format applies to newly created core development documents only. A migration or redirect policy, if needed, will be designed as a separate future effort.

This decision satisfies `docids-260721/REQ-5`.

### `docids-260721/ADR-D7` — Freeze the core document trio after implementation

Requirements and Design documents receive the same `implemented` date only after implementation is complete and verified. From that point, the Requirements, accepted ADR, and Design remain an immutable historical snapshot. Later development uses a new snapshot, while living Specs continue to describe current behavior.

This decision satisfies `docids-260721/REQ-6`.

## Alternatives Rejected

### Continue allocating repository-wide ADR numbers

Rejected because parallel branches must coordinate the next number or renumber files and references during rebase.

### Prefix every reference with the document type

References such as `ADR-slack-260721-D1` were rejected because they scatter documents from the same development effort lexically and make the shared snapshot less prominent.

### Create one ADR file per decision inside a snapshot

Rejected because it reintroduces local allocation and creates unnecessary files. Decision-local `D1`, `D2`, and later identifiers provide stable references within one snapshot ADR.

### Rename existing documents immediately

Rejected because it would break historical and external links and would combine a migration policy with the new-creation policy.

## Consequences

- Parallel development no longer depends on a shared ADR sequence.
- Any core document basename identifies its sibling paths directly.
- Typed references distinguish requirements, decisions, and documents while preserving a compact snapshot identity.
- Documentation validation must recognize both the new snapshot format and legacy ADR/Design files.
- Snapshot validation must model the progressive Requirements-first workflow rather than requiring all three files from the first commit.
- Existing history remains heterogeneous until a separately approved migration is performed.

## Related Documents

- [Shared Development Snapshot Identifier Requirements](../requirements/docids-260721-shared-development-snapshot-identifiers.md)
- [Shared Development Snapshot Identifier Design](../design/docids-260721-shared-development-snapshot-identifiers.md)
