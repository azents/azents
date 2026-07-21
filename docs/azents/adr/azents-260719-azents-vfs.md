---
title: "Run-Scoped Azents Virtual Filesystem Historical Decision Reconstruction"
created: 2026-07-19
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: azents-260719
historical_reconstruction: true
migration_source: "docs/azents/design/run-scoped-azents-vfs.md"
---

# Run-Scoped Azents Virtual Filesystem Historical Decision Reconstruction

- Snapshot: `azents-260719`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/run-scoped-azents-vfs.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### azents-260719/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: URI Contract

The canonical URI shape is:

```text
azents://{mount}/{path...}
```

The first mount is `skills`:

```text
azents://skills/azents/deep-research/SKILL.md
azents://skills/github/review-pull-request/SKILL.md
azents://skills/github/review-pull-request/references/checklist.md
```

Canonicalization requires the lowercase `azents` scheme, a registered lowercase authority/mount, non-empty path segments, no query or fragment, no userinfo or port, no backslash, no dot segment, and no encoded separator or alternate traversal encoding. Path case is significant.

### Explicit source section: CI Policy

Unit, repository, migration, package-build, backend integration, and applicable E2E tests are required. Live external-provider tests remain optional and must skip only for missing credentials; all deterministic VFS tests fail normally.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
