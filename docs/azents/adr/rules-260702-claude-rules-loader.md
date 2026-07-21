---
title: "Claude Rules Loader Historical Decision Reconstruction"
created: 2026-07-02
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: rules-260702
historical_reconstruction: true
migration_source: "docs/azents/design/claude-rules-loader.md"
---

# Claude Rules Loader Historical Decision Reconstruction

- Snapshot: `rules-260702`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/claude-rules-loader.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### rules-260702/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Symlink Policy

Rules discovery may follow symlinks under `.claude/rules`, but the resolved real path must stay inside the source owner root:

- Workspace root rule symlinks must resolve inside `/workspace/agent`.
- Project root rule symlinks must resolve inside that Project root.
- Symlinks resolving outside the owner root are skipped quietly.
- Symlink loops must terminate through realpath/visited-set dedupe.

This intentionally does not support external shared-rules symlinks in the initial product runtime feature.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
