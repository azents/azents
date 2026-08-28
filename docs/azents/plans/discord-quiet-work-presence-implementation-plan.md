---
title: "Discord Quiet Work Presence Implementation Plan"
created: 2026-08-28
tags: [discord, external-channel, implementation, plan]
---

# Discord Quiet Work Presence Implementation Plan

- Requirements: [`discord-260828/REQ`](../requirements/discord-260828-quiet-work-presence.md)
- ADR: [`discord-260828/ADR`](../adr/discord-260828-quiet-work-presence.md)
- Approved Design: [`discord-260828/DESIGN`](../design/discord-260828-quiet-work-presence.md), revision 1
- Approved mechanisms: M1, M2, M3, M4, M5, M6, M7, M8
- Independent reviewer: `/root/quiet-presence-reviewer`
- Design delta: `None`

## Delivery Shape

Use three stacked PRs so canonical state and migration, persistent Gateway presentation,
and final E2E/spec promotion remain independently reviewable while preserving one
approved feature boundary.

1. `discord quiet work presence [1/3]: persist mention-gated tracker visibility`
2. `discord quiet work presence [2/3]: maintain Gateway typing presence`
3. `discord quiet work presence [3/3]: verify and promote quiet work presence`

Create all three PRs before monitoring CI. Do not merge without requester approval.

## Phase 1 — Canonical visibility and Tracker gating

- Mechanisms: M1, M2, M3, M7
- Adds Channel Work schema version 2 and a forward migration that grandfathers existing
  Work as visible.
- Unifies input acceptance so new Discord Work derives visibility from invocation and
  an active hidden Work promotes monotonically on a late mention.
- Gates initial and `channel_action` progress provider effects while preserving hidden
  canonical desired progress.
- Updates focused backend and migration tests.
- Removes unconditional Discord Tracker planning and runtime schema-version-1 support.

## Phase 2 — Gateway typing runtime

- Mechanisms: M4, M5, M6
- Adds a fenced active-typing target projection for one owned Discord connection.
- Extends the current Gateway runner and production `discord.Client` lifecycle with
  per-channel public-SDK typing tasks and PostgreSQL reconciliation.
- Adds shutdown, lease-loss, reconnect, and provider-failure isolation.
- Extends deterministic Gateway test boundaries and focused backend tests.

## Phase 3 — E2E, Specs, and finalization

- Mechanisms: M8 plus validation of M1-M7
- Extends the credential-free Discord provider fake with sanitized typing evidence and
  controllable outcomes.
- Adds required E2E for non-mention hidden Tracker, late mention promotion, direct
  mention, finish/ignore, and Gateway recovery.
- Runs the complete validation matrix and fixes feature defects.
- Updates current External Channel Living Specs.
- Marks Requirements and Design implemented only after validation passes.
- Removes this implementation plan and every phase plan in the final phase.

## Dependencies and Interfaces

- Phase 2 depends on the phase-1 Work schema and active/finished lifecycle.
- Phase 3 depends on phase-1 Tracker semantics and phase-2 typed Gateway typing
  boundary.
- Public API, generated clients, Web UI, `channel_action` input schema, Slack behavior,
  and Scheduled Task Tracker behavior remain unchanged.
- PostgreSQL is the only recovery authority. Redis and process-local tasks are optional
  presentation accelerators only.

## Review and Context Checkpoints

Each phase is reviewed independently by `/root/quiet-presence-reviewer` using the
confirmed Requirements, accepted ADR, approved Design revision 1, current Specs, phase
plan, and stable phase diff. Re-review is required only for Requirements/Design,
security/data-loss, material concurrency/lifecycle, convention, or interface
corrections.

At each phase boundary record implemented mechanisms, changed interfaces, validation,
removal evidence, remaining scope, risks, and blockers before opening the phase PR.

## Validation Matrix

- Backend: Ruff, `ty`, focused and affected Pytest, migration tests.
- Testenv E2E support: Ruff, `ty`, focused support tests.
- Required public E2E: credential-free Discord scenario matrix.
- Static provider SDK boundary checks.
- `/spec-review` before final spec promotion.
- Full CI after all stacked PRs exist.

## Removal Obligations

- Remove unconditional Discord initial Tracker planning.
- Remove hidden-Work `channel_action` progress creation.
- Remove runtime support for Channel Work Toolkit State schema version 1 after the
  migration boundary.
- Replace the absence of Gateway typing lifecycle with the approved reconciled owner.
- Preserve Slack, Scheduled Task, public API, generated client, and Web behavior.

## Rollout and Rollback

- Migration precedes application rollout and marks all existing Work visible.
- New cycles use mention-derived visibility.
- Gateway rollout restores typing for current active Discord Work.
- Downgrade restores unconditional Tracker behavior without provider cleanup.

## External Actions and Blockers

- No live provider credentials or Kubernetes mutations are required.
- No known blocker.
- Design delta: `None`.
