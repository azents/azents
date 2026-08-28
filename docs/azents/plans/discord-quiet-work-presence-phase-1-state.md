---
title: "Discord Quiet Work Presence Phase 1 Execution Plan"
created: 2026-08-28
tags: [discord, external-channel, implementation, plan]
---

# Discord Quiet Work Presence Phase 1 Execution Plan

## Phase Execution Plan

- Phase: `1/3 Canonical visibility and Tracker gating`
- Branch/base: `feature/discord-quiet-work-presence-1-state` → `main`
- PR boundary: Versioned mention-gated Channel Work visibility, migration, ingress
  promotion, and Tracker effect gating
- Inputs: Confirmed `discord-260828/REQ`, accepted `discord-260828/ADR-D1-D2`, approved
  `discord-260828/DESIGN` revision 1
- Deliverables: New Discord Work cycles are hidden or visible from invocation; late
  mentions promote hidden active Work; hidden progress remains canonical without
  provider Tracker effects; existing Work migrates visible
- Non-goals: Gateway typing tasks, provider-fake typing evidence, required E2E, Living
  Spec promotion, Slack changes, Scheduled Task changes, public API changes
- Interfaces: Channel Work Toolkit State schema version 2; one invocation-aware Work
  input-acceptance repository boundary; existing provider-effect operations unchanged
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M7`
- Authority references: `discord-260828/REQ-3`, `REQ-4`, `REQ-5`;
  `discord-260828/ADR-D2`; current External Channel domain and delivery Specs
- Design delta: `None`
- Removal obligations: Unconditional Discord initial Tracker planning; hidden-Work
  `channel_action` progress creation; runtime Channel Work schema-version-1 support
- Absence verification: Repository search and tests prove every Work-state constructor
  supplies visibility, no v1 decoder remains, and hidden Discord Work produces no
  progress create/update/delete effect

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| State and migration | `/root` | `python/apps/azents/src/azents/repos/external_channel/work_state.py`, new Alembic revision, revision pointer, migration tests | Approved M1/M7 | Strict schema v2 and visible backfill | Migration tests, Work-state tests, Ruff, ty |
| Work transitions and Tracker gating | `/root` | `python/apps/azents/src/azents/repos/external_channel/work.py`, focused tests | State schema | Invocation-aware activation/promotion and hidden effect gating | Focused repository tests |
| Ingress integration | `/root` | service `mailbox_ingestion_store.py`, `ingress_queue.py`, `ingress_provisioning.py`; repository `ingress_queue.py`; focused tests | Work transition interface | Direct, first-owner provisioning, and batched invocation evidence drives visibility | Focused repository/service tests |
| Independent review | `/root/quiet-presence-reviewer` | Read-only full phase diff | Stable implementation and checks | Severity-ranked findings or no findings | Requirements/ADR/Design/convention review |

- Integration order: State model and migration → Work repository transition → direct
  ingress → first-owner provisioning → batched ingress → `channel_action` gating →
  focused tests and migration verification
- Independent review: `/root/quiet-presence-reviewer`; review M1/M2/M3/M7, migration
  safety, CAS concurrency, at-most-once projection semantics, Slack/Scheduled regression,
  and test sufficiency from the approved authority documents and stable diff
- Final validation: `uv run ruff check`, `uv run ruff format --check`,
  `uv run ty check --error-on-warning`, focused Pytest for Work state/repository,
  direct and batched ingress, Channel Action, provisioning, and migration
- Scope-drift check: All M1/M2/M3/M7 behavior and removals present; no typing runtime,
  API/UI change, compatibility fallback, new provider operation, or Scheduled/Slack
  behavior enters this phase

## Phase 1 Checkpoint

- Completed behavior: strict Work schema v2, visible backfill, invocation-derived new
  cycles, monotonic late-mention promotion, first-owner provisioning classification,
  hidden progress retention, and Tracker provider-effect gating.
- Changed interfaces: `ensure_active_work()` and `create_configured_binding()` require
  explicit Tracker visibility; provisioning loads the first authoritative queued item.
- Concurrency evidence: late-mention promotion retries a revision race and claims the
  latest desired snapshot exactly once.
- Migration evidence: frozen model-equivalent preflight validates all targeted rows
  before visible/schema update; malformed rows remain unchanged.
- Removal evidence: runtime v1 Work decoding is absent; hidden initial and
  `channel_action` progress paths produce no Tracker effect.
- Validation: 711 External Channel and migration tests passed; Ruff, format, `ty`, and
  `git diff --check` passed.
- Independent review: final re-review returned no findings after three identified
  lifecycle/migration defects were corrected.
- Remaining scope: M4-M6 Gateway typing runtime, M8 provider-fake E2E, Living Spec
  promotion, final validation, and plan cleanup.
- Risks: none blocking; typing cadence and provider rate-limit behavior remain Phase 2.
- Design delta: `None`.
