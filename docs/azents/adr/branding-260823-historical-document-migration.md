---
title: "Historical Document Branding Migration"
created: 2026-08-23
tags: [branding, documentation, migration, architecture]
document_role: primary
document_type: adr
snapshot_id: branding-260823
---

# Historical Document Branding Migration

- Snapshot: `branding-260823`
- Document reference: `branding-260823/ADR`
- Requirements: [branding-260823/REQ](../requirements/branding-260823-historical-document-migration.md)

## Context

The normal Azents documentation lifecycle keeps accepted ADRs and implemented
Requirements and Designs immutable. The requester has explicitly required a complete
repository branding migration that includes those historical records, their
canonical identifiers, provenance records, and generated indexes.

Preserving the existing literals would fail `branding-260823/REQ-1`. Rewriting the
historical documents without explicit authority would violate the documentation
lifecycle. This ADR records the bounded exception and its traceability model.

## Decisions

### branding-260823/ADR-D1. Authorize one brand-only historical rewrite

Authorize one atomic rewrite of accepted ADRs, implemented Requirements and Designs,
and exact provenance records solely to replace the superseded product brand with
Azents naming.

The exception does not authorize changing historical requirements, decisions,
mechanisms, dates, actors, or outcomes. Normal immutability resumes immediately
after verification.

### branding-260823/ADR-D2. Migrate canonical identifiers without aliases

Rename historical filenames and snapshot IDs that contain the superseded brand.
Update every tracked reference and generated index in the same change.

Do not retain compatibility aliases, duplicate files, redirect stubs, or fallback
identifiers inside the repository. Internal consistency and a zero-match result take
precedence over preserving superseded repository paths.

### branding-260823/ADR-D3. Use Git history as literal provenance

Git history and this migration snapshot are the authoritative record of the
pre-migration wording and identifiers. The tracked tree does not retain the
superseded brand merely for provenance.

## Rejected Options

### Preserve immutable historical literals

Rejected because the requester explicitly requires all historical documents to use
Azents naming and the repository-wide search must return zero matches.

### Rewrite content but keep historical filenames and snapshot IDs

Rejected because tracked paths and canonical references would continue exposing
mixed branding and fail `branding-260823/REQ-1` and `REQ-2`.

### Add compatibility aliases

Rejected because aliases would retain the superseded identifiers, create duplicate
document authority, and conflict with the repository's no-legacy-fallback policy.

## Consequences

- Historical document diffs are large but mechanically bounded to branding and
  canonical identifier migration.
- External deep links to renamed files may stop resolving until an external redirect
  mechanism is configured.
- Reviewers can recover exact prior wording and paths from the parent Git commit.
- Future changes to migrated historical snapshots remain prohibited.
