---
title: "Per-Prompt Inference Profile Historical Decision Reconstruction"
created: 2026-07-10
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: promptinferenceprofile-260710
historical_reconstruction: true
migration_source: "docs/azents/design/per-prompt-inference-profile.md"
---

# Per-Prompt Inference Profile Historical Decision Reconstruction

- Snapshot: `promptinferenceprofile-260710`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/per-prompt-inference-profile.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### promptinferenceprofile-260710/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Phase 1: persistence and contracts

- Define shared requested/resolved profile types and enums.
- Generate database migration.
- Update RDB/domain/repository models.
- Add API request/response schemas and regenerate clients.

### Explicit source section: CI policy and evidence

- Unit, type, lint, and deterministic E2E tests are required and fail the change when prerequisites or assertions fail.
- Optional live-provider smoke tests may be skipped only when their documented external credential prerequisite is absent; they do not replace deterministic coverage.
- Required evidence includes test command output, structured E2E run/profile assertions, and mobile/desktop screenshots for layout-sensitive states.

### Explicit source section: Deferred Decisions

- Dynamic-routing inputs, guarantees, and active-run join/re-resolution semantics.
- Explicit `spawn_agent` Model/effort override.
- Rich full AgentRun audit history beyond the latest compact user-message projection.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
