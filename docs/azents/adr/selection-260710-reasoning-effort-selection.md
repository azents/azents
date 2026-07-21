---
title: "Expose Default as a Reasoning Effort Selection"
created: 2026-07-10
tags: [architecture, agent, frontend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: selection-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0111-reasoning-effort-default-selection.md"
---

# selection-260710/ADR: Expose Default as a Reasoning Effort Selection

## Context

Reasoning-capable model targets can advertise different selectable effort levels. A user may switch the Composer from a model that supports the current explicit effort to one that does not. Preserving an unsupported value until run start creates an avoidable failure, while requiring another selection after every incompatible model change adds friction.

The runtime already represents the absence of an explicit reasoning-effort override as `null`. This is a meaningful requested-profile value: the resolved model or provider applies its default behavior rather than Azents selecting another effort level.

## Decision

Expose `Default` as a first-class Composer reasoning-effort selection alongside the effort levels advertised by the selected model preview. `Default` maps to `reasoning_effort: null` and means that the prompt does not request an explicit effort override.

When the user changes Model in the Composer:

- retain the current explicit effort when the new model preview advertises that level;
- otherwise change the visible selection to `Default` before submission;
- hide the effort control when the selected model does not advertise selectable effort levels, using the same `null` requested value.

The Composer must visibly reflect the resulting selection. This is not run-time fallback: the submitted requested profile contains `null`, and run-time resolution remains strict for every non-null explicit effort under [time-260710/ADR](./time-260710-time-target-resolution.md).

Agent configured effort and AgentSession last-used effort may initialize the Composer when valid for its selected target. If an initializer is not supported by the selected target preview, initialize the Composer to visible `Default` rather than carrying an invalid explicit value.

Use localized user-facing labels for `Default`, `Low`, `Medium`, and `High`.

## Rejected options

### Require a new explicit effort after an incompatible model change

This prevents submission until another control is changed and adds friction to ordinary model switching even though provider-default behavior is valid.

### Submit the stale effort and rely on run-time validation

The Composer already has enough capability information to prevent the predictable mismatch. Delaying the failure makes the UI state misleading.

### Silently substitute another explicit effort level

Choosing Low, Medium, High, or another level without user intent changes inference behavior. Only the visible `Default` no-override state is selected automatically.

## Consequences

- Requested-profile comparison treats `null` as the no-override effort value.
- Model changes can visibly reset an incompatible effort to `Default` without blocking submission.
- Run start still explicitly fails if a non-null requested effort is unsupported by the resolved model snapshot.
- The frontend needs capability-aware effort initialization and validation.
- User-message and run provenance distinguish no explicit override from each concrete effort level.

## Migration provenance

- Historical source filename: `0111-reasoning-effort-default-selection.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
