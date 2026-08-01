---
title: "Provider Channel Participation Phase 5 — Lifecycle, Management, Web, and Rollout"
created: 2026-08-01
updated: 2026-08-01
tags: [external-channel, conversation, lifecycle, management, frontend, rollout, implementation]
---

# Provider Channel Participation Phase 5 — Lifecycle, Management, Web, and Rollout

## Phase Execution Plan

- Phase: `5 — Lifecycle, Management, Web, and Rollout`
- Branch/base: `feature/conversation-channel-participation-lifecycle` → `feature/conversation-channel-participation-discord`
- PR boundary: Extend selected-Agent and terminal lifecycle mutations across participation state; project the resulting parent/thread state through management APIs, generated clients, and Web surfaces; reconcile version-2 settings controls for existing connected Bindings; and expose the deployment-controlled rollout gate and sanitized evidence.
- Inputs: Approved `conversation-260801` Requirements, ADR, Design, and multi-phase implementation plan; Phase 1 schema/domain foundation; Phase 2 setup/ingress/parent Session behavior; Phase 3 Slack controls; and Phase 4 Discord controls.
- Deliverables: Locked selected-Agent replacement and clear with participation invalidation and parent-Binding cleanup; route, Agent, connection, and Session lifecycle integration without revival; shared Web User/provider-principal mutation units; expanded impact counts and parent/thread Binding projections; regenerated OpenAPI clients; responsive Web management and Session Channels updates; bounded existing-Binding settings-control reconciliation; rollout enablement and sanitized evidence.
- Non-goals: Deterministic integrated E2E fixture expansion; live provider rollout execution; Living Spec promotion; Requirements/Design implementation markers; implementation-plan cleanup; or merge of any stacked PR.
- Interfaces: Selected-Agent transitions use conversation then participation locks and canonical database lock order; provider I/O remains outside those locks and transactions; terminal settings, claims, interactions, Bindings, Sessions, and delivery evidence are never revived; provider-principal and Azents User provenance remain exactly separated; public API changes originate in route/domain models and generated clients are regenerated from OpenAPI rather than edited; the participation gate remains read-compatible and deployment-controlled.
- Removal obligations: Replace default-row-only selected-Agent replacement/clear with the shared participation terminalization unit; replace thread-only/opaque Binding management projection with explicit parent/thread location and Session navigation; replace the joined-presence-only existing-Binding assumption with a distinct version-2 `binding_settings_available` reconciliation intent; expose the existing disabled backend gate through deployment configuration without removing the compatibility safeguard.
- Absence verification: Repository searches and lifecycle tests prove no selected-Agent removal leaves an active setting, nonterminal claim, linked live interaction, or connected old parent Binding; projection/API/client/UI tests prove parent/thread location is explicit; reconciliation tests prove disconnected and delivered/failed/unknown states are not blindly recreated; generated-client drift and rollout configuration tests prove one source of truth.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Selected-Agent and terminal lifecycle | `/root` | `repos/external_channel/{management,lifecycle,repository}.py`, `services/external_channel/{management,lifecycle,participation}.py`, Session/Agent/connection lifecycle collaborators, focused tests | Phase 1 persistence and Phase 2/3/4 participation mutations | One locked replacement/clear and lifecycle invalidation authority; parent-only disconnect; preserved threads/history; no revival | A-to-B, clear, route removal, Agent lifecycle, connection disconnect, Session archive/restore/purge, actor provenance, cleanup-intent tests |
| Management API and generated contracts | `/root` | `repos/external_channel/management_data.py`, public management routes/models, OpenAPI source/dump, generated Python and TypeScript public clients | Stable lifecycle mutation results and projection fields | Impact counts, selected setting summaries, explicit conversation location, connectedness, Session navigation, Work and delivery evidence | Service/route/OpenAPI tests, `openapi-client-gen`, generated drift checks, Python quality checks |
| Web management and Session Channels | `/root` | `typescript/apps/azents-web/src/features/external-channel-{management,workspace}/**`, `features/session-channels/**`, tRPC router, localization, stories and focused tests | Regenerated TypeScript client and management schema | Readable selected-Agent/location/mode summaries and parent/thread Session Channels states with responsive copy | TypeScript format, lint, typecheck, build, stories, focused tests and rendered-state checks |
| Existing-Binding control reconciliation | `/root` | External Channel repository/service/worker scheduling paths, provider presentation/action collaborators, focused tests | Versioned Slack/Discord binding settings controls from Phases 3–4 | Bounded durable `binding_settings_available` intents for eligible connected Bindings without provider-history rewrite or blind retry | Delivered/failed/unknown/missing/disconnected matrices, idempotency and provider-I/O-after-commit tests |
| Rollout and observability | `/root` | backend config, worker/server/gateway wiring, Helm values/templates and configuration tests, sanitized logs/tests | Read-compatible Phase 1 gate and all runtime consumers | Deployment-controlled enablement while retaining the safeguard; categorical content-free lifecycle evidence | Config/Helm/server/worker/gateway gate tests, sanitized logging assertions, no identifier/content leakage |

- Integration order: Implement and test the shared lifecycle terminalization unit; wire selected-Agent and terminal lifecycle callers; extend projections and API models; regenerate clients; update Web surfaces; add the existing-Binding reconciler; expose rollout configuration and evidence; run cross-interface validation and scope-drift review.
- Independent review: `/root/conversation-260801-independent-reviewer` performs one read-only review against the immutable snapshot, this plan, the stable diff, validation evidence, removal obligations, security boundaries, generated contracts, and non-goals. Required corrections follow the established targeted re-review criteria.
- Final validation: Backend Ruff format/check, full Pyright, focused and full feasible Pytest, migration/schema checks where applicable; OpenAPI dump and Python/TypeScript generated-client drift checks; TypeScript format/lint/typecheck/build, stories and focused tests; Helm lint/tests; lifecycle and removal searches; `git diff --check`; docs validation through commit hooks.
- Scope-drift check: Compare the stable branch against Phase 4 and this plan; remove integrated E2E fixtures, Living Spec promotion, implementation markers, plan cleanup, unrelated provider redesign, live infrastructure mutation, or compatibility-gate removal.
- Context checkpoint: Record completed lifecycle behavior, changed public/generated interfaces, Web states, reconciliation evidence, rollout mechanism, removal absence proof, exact validation, review result, remaining integrated-validation/spec/cleanup scope, risks, and blockers before commit and PR creation.

## Context Checkpoint

- Completed behavior:
  - Multi selected-Agent replacement and clear terminalize the old parent participation setting, setup claim, live interactions, and connected parent Binding under conversation-then-participation locking while preserving thread Bindings, Sessions, Resources, and history.
  - Route, Agent, connection, and Session lifecycle paths apply the designed invalidation, disconnect, preservation, and no-revival behavior.
  - AgentAdmin response-mode mutation updates an active parent participation setting and Binding atomically with Azents User provenance; thread mutation remains Binding-only.
  - Existing connected Bindings receive one bounded `binding_settings_available` intent only when participation rollout is enabled. Any existing pending, attempting, delivered, failed, or unknown attempt prevents recreation, and disconnected or otherwise ineligible Bindings are excluded.
  - Slack and Discord lower that distinct intent to concise controls containing `View session` and `Conversation settings` without repeating joined-presence copy or rewriting provider history.
- Changed interfaces:
  - `ManagedBinding` now uses the typed resource kind and explicit `conversation_location`.
  - Multi default replace and clear return `ManagedChannelDefaultMutation`; clear now returns HTTP 200 with the mutation impact instead of HTTP 204.
  - Multi impact and disconnect projections include participation-setting, setup-claim, and connected-parent-Binding counts.
  - OpenAPI plus Python and TypeScript public clients were regenerated from the public schema.
- Web and rollout:
  - Session Channels distinguishes parent-channel and thread conversations with localized labels.
  - Workspace integrations displays selected-Agent mutation cleanup impact and includes focused-handoff and general stories.
  - Helm exposes `AZ_EXTERNAL_CHANNEL_PARTICIPATION_ENABLED` as a disabled-by-default, deployment-overridable server environment value; the compatibility safeguard remains.
  - Provider-control logs contain aggregate counts only and no provider, Binding, Session, or content identifiers.
- Validation evidence:
  - Backend Ruff format/check and full Pyright passed with zero errors.
  - The focused lifecycle, management, provider-control, delivery, presentation, repository, and route suite passed: 188 tests.
  - The full backend suite passed: 3,836 tests.
  - Python generated public-client tests passed: 623 tests.
  - OpenAPI dump, Python client generation, and TypeScript client generation completed successfully in sequence.
  - Web Prettier, ESLint, typecheck, production build, and Storybook build passed.
  - Helm render tests passed: 43 tests.
  - Web unit tests passed 139 of 140; the one failure is the unchanged pre-existing `continuationPresentation` fixture mismatch and is assigned to integrated validation in PR 8 with the existing stack E2E failures.
  - Independent review found one Web impact-preview under-reporting Warning. Route removal and connection disconnect now expose participation-setting, setup-claim, and connected-parent-Binding counts in all supported locales; targeted re-review found no remaining Critical or Warning findings.
  - `git diff --check` passed.
- Removal and absence evidence:
  - Selected-Agent replacement and clear no longer use default-row-only mutation.
  - Repository searches and tests cover terminal participation state and preserved thread state.
  - A distinct `binding_settings_available` origin is now consumed by the bounded Worker drain; terminal evidence is not retried and disconnected Bindings are absent from reconciliation.
  - Generated TypeScript output has no tracked drift after regeneration.
- Remaining scope:
  - Commit and open PR 7 against `feature/conversation-channel-participation-discord`.
  - PR 8 owns deterministic E2E/testenv expansion, the unchanged Web unit fixture mismatch, integrated removal verification, and full-stack CI stabilization.
  - PR 9 owns Living Spec promotion and implementation markers; PR 10 removes implementation plans.
- Risks and blockers:
  - The rollout gate must remain disabled until every deployed API, Worker, and gateway process runs a compatible binary.
  - No live rollout, merge, or infrastructure mutation is authorized in this phase.
