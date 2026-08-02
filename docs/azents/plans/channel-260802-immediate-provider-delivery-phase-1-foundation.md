---
title: "Immediate External Channel Provider Delivery Phase 1 Execution Plan"
created: 2026-08-02
updated: 2026-08-02
tags: [external-channel, slack, discord, backend]
---

# Phase Execution Plan

- Phase: `1 — Provider contract foundation`
- Branch/base: `feat/immediate-provider-delivery-foundation` → `main`
- PR boundary: Introduce process-local direct-effect contracts and remove durable
  Delivery Attempt identity from provider-facing APIs while preserving the current
  single outbox authority and all current behavior.
- Inputs: confirmed `channel-260802/REQ`, accepted `channel-260802/ADR`, approved
  `channel-260802/DESIGN` revision 1, and the multi-phase implementation plan.
- Deliverables:
  - provider-facing target contract without a Delivery Attempt identity;
  - bounded process-local operation key used by Discord nonce generation;
  - direct effect plan and sanitized outcome types usable by Phase 2;
  - current durable service adapted through an explicit boundary;
  - focused tests proving unchanged provider request and result behavior.
- Non-goals:
  - changing the `channel_action` Tool result;
  - changing persistence or creating a migration;
  - removing Action/Delivery records, recovery, Worker, management history, or UI;
  - enabling direct Tool or Control execution;
  - OpenAPI, generated-client, Web, E2E, or Living Spec changes.
- Interfaces:
  - current durable `ChannelDeliveryTarget` may retain attempt status and identity
    internally, but provider presentation and provider client calls receive only the
    process-local provider target and operation key;
  - Discord nonce remains deterministic for one current operation key;
  - Slack and Discord outcome classification remains
    `delivered | failed | unknown`;
  - no new state, setting, runtime mode, retry, fallback, or authority is reachable.
- Approved Design mechanisms: `M2`, `M6`; local prerequisites for `M1`, `M5`, `M7`,
  `M10`
- Authority references: `channel-260802/ADR-D1`,
  `channel-260802/REQ-1`, `channel-260802/REQ-3`,
  `channel-260802/REQ-4`, `channel-260802/REQ-6`
- Design delta: `None`
- Removal obligations: None in this preparatory phase.
- Absence verification: Confirm no direct executor is reachable and all durable
  Action/Delivery call sites remain the sole authority until Phase 2.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Provider contracts | Primary agent | `python/apps/azents/src/azents/repos/external_channel/work_data.py`, new or existing provider-contract data module, focused tests | Approved interfaces | Process-local target/plan/outcome types and durable-to-provider mapping | Focused Ruff, Pyright, data/contract tests |
| Provider adapters | Primary agent | `python/apps/azents/src/azents/services/external_channel/{channel_action.py,discord_delivery.py,presentation.py}`, focused tests | Provider contracts | Provider-facing APIs use operation key and target without attempt identity | Channel Action, Discord delivery, presentation tests |
| Integration and plans | Primary agent | This phase plan, implementation plan, approved Design approval record | Provider work | Stable Phase 1 diff and checkpoint | Full backend checks and diff audit |

- Integration order:
  1. Define the process-local provider target, effect plan, and outcome contracts.
  2. Add conversion from the current durable target at the orchestration boundary.
  3. Update presentation and Discord delivery APIs to consume the new contract and
     operation key.
  4. Update focused tests and run backend validation.
  5. Audit that runtime behavior, persistence, Tool/API contracts, and recovery
     authority are unchanged.
- Independent review: Request GitHub review from `hardtack` on the complete Phase 1
  PR. Review criteria are Design delta, no second authority, no provider behavior
  change, no secret exposure, stable Discord duplicate fence, and complete test
  adaptation.
- Final validation:
  - `cd python/apps/azents && uv run ruff check --fix .`
  - `cd python/apps/azents && uv run ruff format .`
  - `cd python/apps/azents && uv run pyright`
  - focused Channel Action, Discord delivery, presentation, and repository data tests
  - `cd python/apps/azents && uv run pytest`
  - `git diff --check`
- Validation evidence:
  - changed-file and full-backend Ruff check/format passed;
  - full backend Pyright passed with zero errors and warnings;
  - focused provider contract, Channel Action, Discord delivery, and presentation
    tests passed: `60 passed`, `3 warnings`;
  - full backend pytest passed: `3850 passed`, `6 warnings`;
  - `git diff --check` passed;
  - Discord create and multipart requests retain the exact prior 25-character nonce
    bytes for the same current durable operation while the provider client receives
    no Delivery Attempt identifier.
- Scope-drift check: Phase 1 contains only behavior-preserving provider-contract
  preparation. Any persistence, public result, management, Worker, lifecycle,
  generated-client, Web, E2E, or Spec change moves to Phase 2 or Phase 3.
- Scope-drift result:
  - approved provider target, operation-key, effect-plan, mutation-outcome, and
    identifier-free effect-outcome foundations are present;
  - no persistence model, repository authority, Worker, Tool result, public API,
    generated client, Web, E2E, migration, or Living Spec behavior changed;
  - no direct executor, retry, fallback, mode, setting, or second authority was
    added; and
  - `ChannelDeliveryTarget` and current claim/start/settle/recovery paths remain the
    sole reachable delivery authority until Phase 2.
- Context checkpoint:
  - completed behavior: provider presentation and Discord create/file APIs consume
    process-local `ProviderTarget` and `ProviderOperationKey`; provider-specific
    results normalize to one `ProviderMutationOutcome`;
  - changed interfaces:
    `DiscordDeliveryClient.create_message` and `create_file_message` now receive an
    opaque operation key, while repository and service entry points retain their
    current durable IDs;
  - evidence: validation results above plus source searches showing no
    `delivery_attempt_id` field in `provider_effect.py` or Discord delivery client;
  - remaining scope: the complete Phase 2 atomic direct-execution, persistence,
    Worker, lifecycle, API, generated-client, Web, and migration cutover;
  - risks: Phase 2 must replace the current durable-to-provider mapping atomically
    so this preparatory boundary never becomes a second authority;
  - blockers: None;
  - Phase 2 base: the final reviewed Phase 1 PR head commit.
