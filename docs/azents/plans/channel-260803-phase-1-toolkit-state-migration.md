---
title: "Channel 260803 Phase 1 Toolkit State Migration Plan"
created: 2026-08-03
tags: [external-channel, toolkit-state, implementation]
---

# Channel 260803 Phase 1 Toolkit State Migration

## Phase Execution Plan

- Phase: `1 of 2 — Toolkit State migration`
- Branch/base: `design/channel-work-ignore` → `origin/main`
- PR boundary: `Binding-specific Toolkit State becomes the only Channel Work and provider-projection authority while finish and continue behavior remains unchanged.`
- Inputs: `Confirmed channel-260803 Requirements, accepted ADR-D1, approved Design revision 1, implementation plan`
- Deliverables: `Typed state/store, complete reader/writer cutover, reversible destructive migration, legacy storage removal, updated current Specs, regression evidence, open PR 1`
- Non-goals: ``ignore`, turn provenance, selective-response prompt changes, provider-specific behavior changes, public API changes, deployment or merge`
- Interfaces: `external_channel/channel_work:{binding_id}; stable work_cycle_id; cycle-and-revision provider settlement; unchanged ManagedWork and Channel Action result contracts`
- Approved Design mechanisms: `M1, M2, M3, M4, M5, M6, M10, M11`
- Authority references: `channel-260803/REQ-5, channel-260803/ADR-D1, unchanged External Channel delivery and lifecycle Specs`
- Design delta: `None`
- Removal obligations: `Dedicated Work/projection tables and ORM models, table-shaped CRUD and fixtures, all legacy readers/writers, Work lifecycle manifest entry, route-owned Work finalizer check`
- Absence verification: `Migration/schema assertions plus repository-wide search for removed table names and ORM symbols`

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Typed Work state and CAS store | `/root/phase1-work-core` | `python/apps/azents/src/azents/repos/external_channel/work_state.py`, `work.py`, `work_data.py`, focused tests, and `channel_action.py` only for interface adaptation | Approved state identity | Typed current/latest state and mutation API; actions and effects use Toolkit State | Focused state/repository/service tests, Ruff, Pyright |
| Ingress, management, and lifecycle cutover | `/root/phase1-lifecycle` | External Channel generic repository, management, lifecycle, ingestion, lifecycle registry/finalizers, focused tests | Typed store interface | Existing ingress, management, lifecycle, purge, and finalizer outputs from canonical state | Management, lifecycle, purge, finalizer, ingestion tests |
| Schema migration and removal | `/root/phase1-schema` | RDB models/tests, generated Alembic migration and revision file, migration tests, related Living Specs | Stable payload contract | Backfill, drop, downgrade reconstruction, no legacy model, current Specs | Upgrade/downgrade tests, schema inspection, docs validation |
| Integration and deterministic regression | `/root` | Cross-workstream interfaces, remaining affected tests and E2E fixtures | All owner outputs | Stable PR diff with no legacy authority or PR 2 behavior | Full focused matrix, Ruff, Pyright, spec review, E2E, absence audit |

- Integration order: `typed state/store → runtime cutover → management/lifecycle cutover → generated migration and model removal → tests/specs → absence audit`
- Independent review: `/root/channel-260803-reviewer performs read-only review against REQ-5, ADR-D1, Design M1-M6/M10/M11, this phase contract, security/data-loss risks, migration reversibility, legacy absence, and behavior preservation; output is a findings report with severity and required corrections.`
- Final validation: `Ruff format/check, Pyright, focused Pytest suites, migration upgrade/downgrade tests, docs snapshot validation, spec review, deterministic External Channel regression tests where available, git diff --check, repository absence search`
- Scope-drift check: `All approved PR 1 mechanisms and removals are present; no ignore/provenance/prompt behavior or second authority is added.`
- Context checkpoint: `At phase completion record canonical state interfaces, migration revision, removed paths, validation evidence, reviewer result, open PR URL, and the exact PR 2 base. Current risks are migration lock duration and bounded CAS conflict handling; there are no blockers.`
