---
title: "Provider Channel Participation Phase 2 — Setup, Ingress, and Parent Session"
created: 2026-08-01
updated: 2026-08-01
tags: [external-channel, conversation, backend, implementation]
---

# Provider Channel Participation Phase 2 — Setup, Ingress, and Parent Session

## Phase Execution Plan

- Phase: `2 — Setup, Ingress, and Parent Session`
- Branch/base: `feature/conversation-channel-participation-ingress` → `feature/conversation-channel-participation-schema`
- PR boundary: Implement the provider-neutral setup state machine, latest-source replay, location-aware ingestion, and parent-channel Session behavior while leaving provider-native Slack and Discord controls to later phases.
- Inputs: Approved `conversation-260801` Requirements, ADR, and Design; the multi-phase implementation plan; and Phase 1 schema/domain foundation from PR 3.
- Deliverables: Setup-only admission before location selection; latest eligible source replacement; idempotent location selection and replay recovery; setup-linked Multi selector and restricted Allow branches with a typed provider-control continuation; explicit parent/thread Resource resolution; one parent Binding/root Session; existing thread precedence; concrete response-mode copy; transition and concurrency fencing.
- Non-goals: Slack Slash Commands, manifest changes, final Slack UI copy, Discord command reconciliation or UI, provider-specific parent delivery lowering, lifecycle invalidation, management/OpenAPI/Web projections, rollout enablement, integrated E2E fixtures, Living Spec promotion, and plan cleanup.
- Interfaces: Participation lock key `(connection_id, provider_parent_channel_id)`; setup operation and replay boundary discriminators; repository generation/source-revision compare-and-set; location-aware Resource resolution with no thread fallback; existing conversation position and canonical mailbox authorities; provider I/O outside all locks and transactions.
- Removal obligations: Replace eager unconfigured top-level Binding/Session/mailbox admission; replace thread-only Resource resolution; prevent setup-linked Access Allow and selector selection from entering legacy Binding replay.
- Absence verification: Focused side-effect-absence and branch-discriminator tests; exhaustive Resource-type matching; repository/code searches showing no eager top-level Binding path or setup-linked calls to legacy replay.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Participation coordination and service | `/root` | `services/external_channel/participation*.py`, participation lock/dependencies, repository DTO operations as required | Phase 1 setting and claim contracts | Authorized setup creation/replacement, route assignment, location selection, setting mutation, and typed outcomes | Focused service and lock tests; Ruff; Pyright |
| Ingress and conversation resolution | `/root` | `mailbox_ingestion_store.py`, `ingestion.py`, ingestion DTOs/dependencies/tests | Participation service and replay boundary | Pre-history setup gate, configured parent/thread resolution, final state revalidation, concrete response-mode copy, selected-replay priority | Side-effect absence, position, mailbox, wake, parent/thread, stale-generation, and concurrency tests |
| Selector, access, and replay integration | `/root` | `selector.py`, `interaction.py`, `access.py`, `ingestion_replay.py`, focused tests | Setup claim service and ingestion continuation contract | Setup-linked selector assigns route only; setup-linked Allow grants without Binding and returns typed pending-location state for later provider controls; selected continuation recovery and completion | Focused selector/access/replay tests and legacy-path regression tests |
| Parent Session and integration validation | `/root` | External Channel repository/service tests and existing Session/mailbox collaborators only where required | Integrated Phase 2 behavior | One parent Resource/Binding/root Session, later top-level reuse, thread isolation, transition behavior, recovery convergence | Focused PostgreSQL tests; applicable backend Pytest; Ruff; Pyright; scope/absence audit |

- Integration order: Add coordination/typed contracts; replace ingress preparation and acceptance resolution; connect setup selection/replay; split selector and access setup branches; add parent Session behavior; validate concurrency and recovery; run final checks.
- Independent review: `/root/conversation-260801-independent-reviewer` performs one read-only review against the immutable snapshot, this phase plan, owned diff, validation evidence, removal obligations, and non-goals. Required corrections are limited to Requirements/Design, security or data-loss, and material convention/interface defects; targeted re-review uses the same reviewer only when those criteria apply.
- Final validation: Changed-file `uv run ruff format --check` and `uv run ruff check`; `uv run pyright`; focused setup/ingress/access/selector/replay/repository tests; applicable full backend Pytest if feasible; `git diff --check`; docs index validation; removal searches.
- Scope-drift check: Compare the stable branch diff with this plan and Phase 2 Design outcomes; remove provider-specific controls, lifecycle/API/Web/rollout, integrated E2E, Living Spec, or cleanup work accidentally included.
- Context checkpoint: Record completed setup and ingestion behavior, changed typed interfaces, exact validation evidence, removals and absence proof, remaining provider-control scope, relevant paths, and known risks before commit and PR creation.

## Phase Checkpoint

- Completed behavior: Eligible unconfigured top-level invocations create or replace only route-neutral setup state; selected setup replay is prioritized before newer parent ingress; Channel selects one parent Resource/Binding/root Session; Threads retains the source thread Resource; exact existing thread Bindings remain authoritative; setup-linked selector and Allow paths create no Binding or Session; replay completion is generation- and source-revision-fenced.
- Changed interfaces: Added the namespaced participation lock and scope; typed setup source projection and replay boundary; `setup_continuation` ingestion operation; priority recovery preparation; provider-neutral location selection result; and `ExternalChannelSetupContinuation` for later Slack/Discord control consumption after restricted Allow.
- Validation evidence:
  - Changed-file Ruff format and lint passed.
  - Whole-subproject Pyright passed with `0 errors, 0 warnings`.
  - External Channel service and repository suite passed with `515 passed`.
  - Whole backend suite passed with `3787 passed`; six existing dependency or SQLAlchemy warnings remained.
  - Focused PostgreSQL setup-claim selection, recovery listing, and completion checks passed.
  - Independent read-only review found no Critical findings. Two Warnings were corrected, and targeted re-review found no remaining Critical or Warning findings.
- Removal and absence evidence: Setup-required acceptance tests assert no Binding, root Session, Work, mailbox enqueue, or wake transition; setup selector tests assert no Binding lookup or creation; setup Allow tests assert no Binding, Session, or legacy replay; provider history ordering tests assert I/O occurs after both locks are released; code search found no selector or participation-service Binding/Session creation path.
- Scope drift: None. Provider command registration, final Slack/Discord location controls and copy, lifecycle invalidation, management/OpenAPI/Web changes, rollout enablement, integrated E2E, Living Spec promotion, and cleanup remain in later phases.
- Remaining context: Phase 3 must consume the typed setup continuation and lower final Slack controls without moving setting, mailbox, wake, or AgentRun authority into provider delivery. Phase 4 replaces the temporary non-interactive Discord Agent-selected handoff with authenticated location controls.
