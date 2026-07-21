---
title: "Legacy Snapshot Identifier Migration Design"
created: 2026-07-21
implemented: 2026-07-21
tags: [documentation, migration, architecture, testing]
document_role: primary
document_type: design
snapshot_id: migration-260721
---

# Legacy Snapshot Identifier Migration Design

- Snapshot: `migration-260721`
- Requirements: `migration-260721/REQ`
- ADR: `migration-260721/ADR`
- Requester confirmation: approved on Tuesday, July 21, 2026 (KST).

## Overview

This design applies the approved historical documentation migration while preserving semantic source content and making provenance explicit.

## Migration Matrix

- 196 legacy ADR files become independent primary snapshot ADRs.
- 45 exact one-to-one ADR/Design pairs and 4 strongest-evidence canonical one-to-many Designs use shared basenames.
- 108 Design-only records become independent historical Requirements/ADR/Design trios, except the already canonical `docids-260721` snapshot.
- 56 many-to-one Designs and remaining secondary/supporting records retain descriptive filenames with explicit supporting roles.
- 118 irreducible duplicate references point to the ambiguity manifest.

## Validation

The validator rejects numeric ADR filenames, validates primary sibling relationships and implementation-date parity, permits only explicit supporting Design exceptions, and rejects unapproved bare legacy tokens.

## Test Strategy

Run the documentation generator/check, migration-specific structural tests, Python compilation, link/reference scans, and the full relevant unittest suite. No runtime E2E behavior changes are introduced.

## Implemented

This field is intentionally added only after complete local verification.
