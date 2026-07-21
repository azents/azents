---
title: "Legacy Snapshot Identifier Migration Requirements"
created: 2026-07-21
implemented: 2026-07-21
tags: [documentation, migration, architecture]
document_role: primary
document_type: requirements
snapshot_id: migration-260721
---

# Legacy Snapshot Identifier Migration Requirements

- Snapshot: `migration-260721`
- Requester confirmation: approved on Tuesday, July 21, 2026 (KST).

## Problem

Existing ADR filenames and references use a repository-wide numeric sequence, including duplicate numbers, while related historical Design and Requirements records use unrelated names.

## Primary Actor

A maintainer migrating the historical documentation set.

## Primary Scenario

The maintainer converts legacy core records to deterministic dated snapshots without inventing product intent or losing historical links.

## Goals

- Preserve explicit historical decisions and Design intent with provenance.
- Make every migrated primary snapshot discoverable through one basename.
- Preserve supporting records and route irreducible references to an ambiguity manifest.

## Non-goals

- Rewrite historical product decisions.
- Infer missing requester confirmation or acceptance criteria.
- Change current Specs, Notes, Issues, or runtime behavior.

## Requirements

- Reconstruct historical Requirements only from explicit source text and mark unknowns.
- Migrate one-to-one ADR/Design pairs and independent Design-only snapshots.
- Keep many-to-one and secondary Designs as explicit supporting records.
- Rewrite resolvable references to concrete snapshot references and irreducible references to precise ambiguity-manifest anchors.
- Remove generic legacy ADR/primary-Design acceptance after all invariants pass.

## Fixed Constraints

- Historical snapshot dates are no later than 2026-07-21 KST.
- No arbitrary numeric collision suffixes.
- No bare legacy ADR IDs outside the approved ambiguity/provenance manifests.
