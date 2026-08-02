---
title: "Immediate External Channel Provider Delivery Phase 3 Execution Plan"
created: 2026-08-02
tags: [external-channel, slack, discord, testenv, documentation, validation]
---

# Phase Execution Plan

- Phase: `3 — Validation, Spec promotion, and plan cleanup`
- Branch/base:
  `feat/immediate-provider-delivery-validation` →
  `feat/immediate-provider-delivery-cutover@2dd71194c`
- PR boundary: Prove the complete immediate provider-delivery cutover through
  deterministic Slack and Discord journeys, promote the verified behavior into
  Living Specs, mark the approved snapshot implemented, and remove temporary
  implementation plans.
- Inputs:
  - confirmed `channel-260802/REQ`;
  - accepted `channel-260802/ADR`;
  - approved `channel-260802/DESIGN` revision 1 and mechanisms `M1`–`M12`;
  - Phase 1 provider contracts at `9a10f88d1`;
  - Phase 2 atomic cutover at `2dd71194c`; and
  - current External Channel, Toolkit, authorization, lifecycle, and management
    Living Specs plus deterministic E2E/provider-fake substrate.
- Deliverables:
  - deterministic Slack and Discord E2E evidence for immediate ordered Tool
    outcomes, confirmed failure, ambiguity, no replay, and current Work projection;
  - deterministic evidence that control failures do not gate mailbox admission,
    Session wake, AgentRun completion, access decisions, disconnect, or archive;
  - Discord Runtime multipart publication evidence with bounded sanitized file
    counts and byte counts;
  - management/public-client/Web assertions proving delivery history is absent while
    current Work projection remains;
  - integrated validation and authorized implementation-defect corrections only;
  - current Living Specs describing direct execution and owner-local projection;
  - matching `implemented: 2026-08-02` dates on Requirements and Design after
    verification; and
  - removal of the feature implementation plan and all phase execution plans.
- Non-goals:
  - new product behavior, persistence, provider modes, settings, or interfaces;
  - retry, replay, compensation, recovery, fallback, compatibility, queue, or
    provider-operation history;
  - direct product database mutation in E2E;
  - live Slack or Discord credential tests, deployment, merge, or provider mutation;
  - changes to confirmed Requirements, accepted ADR decisions, or approved material
    mechanisms beyond the implementation-date marker.
- Interfaces:
  - `channel_action` input remains unchanged;
  - normal Session history is the only durable Agent-requested execution evidence;
  - Tool output retains ordered provider-neutral `delivered | failed | unknown |
    not_attempted` outcomes without Action, Delivery, provider, payload, credential,
    file, identifier, or URL evidence;
  - non-Tool controls execute at most once after canonical commit and cannot gate
    canonical state;
  - current Work/access projection remains owner-local and management exposes no
    `ManagedDelivery` or `deliveries`; and
  - E2E state is created only through public APIs, UI-equivalent calls, signed
    provider inputs, Runtime APIs, and provider fakes.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`,
  `M9`, `M10`, `M11`, `M12`
- Authority references: `channel-260802/REQ-1` through `REQ-7`,
  `channel-260802/ADR-D1`, `channel-260802/ADR-D2`, approved Design revision 1,
  unchanged authorization/file-authority behavior, documentation lifecycle rules,
  and testenv no-direct-DB-write convention.
- Design delta: `None`
- Removal obligations: Promote delivery-ledger Specs to direct execution, verify the
  complete Phase 2 removal boundary, and delete the temporary implementation and
  phase plans after validation and snapshot promotion.
- Absence verification:
  - public OpenAPI/generated clients and management responses contain no
    `ManagedDelivery`, `deliveries`, Action, or provider-operation history;
  - code/schema searches contain no reachable Action/Delivery model, table, enum,
    Worker, recovery, replay, lifecycle intent, or compatibility authority;
  - provider-fake evidence records at most the expected immediate calls and no later
    background mutation; and
  - updated Specs contain no current-behavior claim that durable Action/Delivery or
    provider-control Worker authority remains.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Deterministic direct-outcome E2E | Primary agent | `testenv/azents/e2e/src/tests/azents/public/test_external_channels.py`; External Channel AIMock evidence helpers | Phase 2 Tool result and management contract | Slack/Discord Session-history, ordered outcome, projection, failure, unknown, and no-replay assertions | Focused deterministic E2E, E2E Ruff/format/Pyright |
| Provider fake and Runtime file evidence | Primary agent | `testenv/azents/e2e/src/support/{slack_provider_fake.py,discord_provider_fake.py}` and focused fake tests when support changes | Existing sanitized fake scenarios and Runtime provider fixture | Bounded failure/ambiguity/control/multipart evidence without payloads or secrets | Fake unit tests, focused Runtime-provider External Channel E2E |
| Control and lifecycle E2E | Primary agent | Existing External Channel access, disconnect, archive, Slack/Discord management journeys in the E2E file | Direct post-commit controls and in-memory cleanup plans | Canonical success with at-most-once provider create/delete/presence/progress cleanup | Focused deterministic E2E and provider request-count assertions |
| Spec promotion | Primary agent | `docs/azents/spec/domain/**`; `docs/azents/spec/flow/**` selected by `/spec-review` | Stable implementation and E2E evidence | Current direct-execution, owner-local projection, lifecycle, management, and Tool contracts | `/spec-review`, docs validation, stale-authority searches |
| Snapshot promotion and cleanup | Primary agent | Snapshot Requirements/Design frontmatter; `docs/azents/plans/channel-260802-immediate-provider-delivery-*.md` | Integrated validation and spec promotion | Matching implementation dates and no temporary feature plans | Snapshot validator, generated index hook, plan absence search |
| Integration and defect correction | Primary agent | Phase 2 product paths only when validation proves an implementation defect | Reproducible failing evidence within approved mechanisms | Minimal authorized correction without new behavior or authority | Affected focused checks plus invalidated full validation lanes |

- Integration order:
  1. Commit this tracked Phase 3 plan on the Phase 2 base.
  2. Extend provider-neutral evidence helpers and deterministic journeys for direct
     Tool outcomes, current projection, failures, ambiguity, and no background replay.
  3. Extend access, disconnect, archive, and control-failure assertions; add Discord
     Runtime multipart publication using the existing Runtime provider fixture.
  4. Run focused E2E and fake tests, fix only reproduced implementation defects, and
     rerun evidence invalidated by each correction.
  5. Run the full deterministic and Runtime-provider External Channel validation,
     backend/client/TypeScript consistency checks, migration test, and removal audit.
  6. Run `/spec-review`, promote all impacted Living Specs, and verify no stale
     delivery-ledger authority remains.
  7. Add matching verified implementation dates to Requirements and Design, delete
     all matching feature plans, run final docs/snapshot validation, and commit the
     stable Phase 3 diff.
  8. Open the third stacked PR, request `hardtack`, then monitor the complete PR stack
     and correct CI failures without merging.
- Independent review:
  - reviewer: GitHub reviewer `hardtack`;
  - scope: complete Phase 3 diff against `channel-260802/REQ`, ADR-D1/D2, approved
    Design revision 1, Phase 1/2 interfaces, current implementation, this plan, and
    deterministic E2E evidence;
  - criteria: complete M1–M12 verification, no direct DB setup, trustworthy sanitized
    evidence, no missing failure/ambiguity/control/lifecycle/file boundary, accurate
    Living Specs, correct immutable-snapshot promotion, complete plan cleanup, and no
    new delivery authority;
  - inputs: authority documents, Phase 1/2 PRs, phase plans, E2E/fake diffs, validation
    results, absence searches, spec review, and the complete Phase 3 diff;
  - output: grounded Critical/Warning findings or explicit no findings; targeted
    re-review only for Requirements/Design, security/data-loss, or material
    convention/interface corrections.
- Final validation:
  - `cd testenv/azents/e2e && uv run ruff check --fix .`
  - `cd testenv/azents/e2e && uv run ruff format .`
  - `cd testenv/azents/e2e && uv run pyright`
  - focused Slack/Discord provider-fake tests
  - focused deterministic External Channel E2E
  - focused Runtime-provider External Channel E2E, including Discord multipart files
  - `cd testenv/azents/e2e && uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src`
  - `cd python/apps/azents && uv run ruff check --fix . && uv run ruff format . && uv run pyright`
  - affected backend tests plus populated migration round-trip test
  - `cd python/libs/azents-public-client && uv run pytest -q`
  - `cd typescript && pnpm run format && pnpm run lint && pnpm run typecheck && pnpm run build`
  - OpenAPI/generated-client consistency checks
  - `/spec-review` and docs snapshot validation
  - repository-wide legacy schema/code/API/UI/Spec absence searches
  - `git diff --check`
- Scope-drift check:
  - verify every M1–M12 mechanism and all remaining validation/spec/cleanup obligations;
  - reject new persistence, queue, retry, replay, recovery, compensation, fallback,
    compatibility, feature flag, provider mode, setting, history, or source of truth;
  - keep all evidence sanitized and prevent provider payloads, credentials, raw IDs,
    URLs, file bytes, or sensitive content from entering assertions or reports;
  - limit product-code corrections to defects demonstrated by approved validation;
    and
  - return any material behavior/state/interface mechanism outside approved Design
    authority to feature design before continuing.
- Context checkpoint: Record Phase 2 base `2dd71194c`, each deterministic scenario and
  result, any corrected defect and invalidated evidence, full validation commands,
  migration/removal absence evidence, promoted Spec versions and paths, matching
  implementation date, removed plan paths, review findings, final PR/CI state, risks,
  and blockers.
