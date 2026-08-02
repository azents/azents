---
title: "External Channel Automatic Title Phase 4 Deterministic E2E Execution Plan"
created: 2026-08-02
updated: 2026-08-02
tags: [external-channel, discord, slack, title, testenv, e2e]
---

# Phase Execution Plan

- Phase: `4 — Deterministic E2E and integrated validation`
- Branch/base:
  `feat/external-channel-title-deterministic-e2e` →
  `feat/external-channel-title-reconciliation-lifecycle`
- PR boundary: Extend the credential-free Discord fake and deterministic model
  fixtures, prove the complete Slack and Discord automatic-title journeys through
  user-facing paths, and record integrated validation for M1 through M8.
- Inputs:
  - approved `title-260802/REQ`;
  - accepted `title-260802/ADR-D1` through `ADR-D6`;
  - approved `title-260802/DESIGN` revision `5`;
  - Phase 1 persistence foundation from PR #1093;
  - Phase 2 admission and provider proof from PR #1094;
  - Phase 3 title reconciliation and lifecycle from PR #1095;
  - the existing deterministic Discord and Slack provider fakes, AIMock fixture
    loader, public External Channel API/Gateway journeys, and credential-free CI
    lane.
- Deliverables:
  - bounded Discord fake thread state with exact root flags, thread identity,
    parent/root/Guild relationship, owner, name, and
    `thread_metadata.create_timestamp`;
  - exact direct thread-channel GET and name-only PATCH fake routes matching the
    Phase 3 Discord client contract;
  - controlled create/read/PATCH outcome sequences, operation-specific crash and
    race barriers, test-only human takeover mutation, request counters, and
    sanitized bounded final-state evidence;
  - focused fake contract tests for exact-root consistency, rich thread payloads,
    direct GET/PATCH, ambiguity, retry sequences, barriers, takeover mutation, and
    evidence redaction;
  - deterministic lightweight-model fixtures for authorized External Channel title
    prompts and stable generated titles;
  - a Discord new-root journey proving immediate admission and execution,
    automatic Session-title convergence, exact direct or adopted provider proof,
    and one final thread-name PATCH;
  - a Slack new-Session journey proving the same Session-title convergence without
    any Discord projection or provider title mutation;
  - deterministic coverage for context and Bot exclusion, safe attachment
    metadata, Access-Allow replay, existing or later Sessions, manual title edits,
    pre-existing Discord threads, human takeover, recoverable provider failures,
    lifecycle revocation, and mixed-version conservative adoption;
  - complete credential-free testenv and affected backend regression evidence plus
    an M1–M8 and removal-obligation conformance audit.
- Non-goals:
  - live Discord or Slack credentials, live-provider mutation, or a live test as a
    substitute for deterministic evidence;
  - direct database writes from E2E scenarios, runners, or helpers;
  - new product API, OpenAPI client, schema, frontend, Helm, environment,
    configuration, process, queue, Redis dependency, Worker mode, or fallback;
  - changing Phase 1–3 backend contracts unless deterministic integration exposes a
    product defect within the approved Design;
  - asserting an impossible atomic Discord compare-and-set guarantee inside the
    accepted GET/PATCH race window;
  - Living Spec promotion, snapshot `implemented` marking, or plan cleanup.
- Interfaces:
  - configured and provider-created fake thread objects use exact bounded Discord
    fields: `id`, `parent_id`, root-message identity, Guild identity, `owner_id`,
    `name`, `flags`, and `thread_metadata.create_timestamp`;
  - an exact-root read reports `HAS_THREAD` consistently with the complete thread
    object; inconsistent or incomplete provider data remains fail-closed evidence;
  - provider-created threads retain the requested normalized provisional name, the
    active fake Bot owner, and deterministic creation metadata;
  - `GET /api/v10/channels/{thread_id}` returns the exact current thread object and
    `PATCH /api/v10/channels/{thread_id}` accepts only a bounded `name` mutation;
  - `api_scenarios` and `api_scenario_sequences` control `create_thread`, root
    reads, direct thread reads, and thread-name updates without changing product
    retry semantics;
  - one bounded barrier contract supports provider operations needed to prove
    preflight, committed-create recovery, GET-before-PATCH takeover, and lifecycle
    revocation ordering; timeout, reset, and `finally` release prevent deadlocks;
  - test-only thread mutation changes current owner or name without resetting
    provider evidence or being counted as an Azents provider mutation;
  - `/__testenv/state` exposes only bounded request counts, operation identities,
    safe outcome categories, thread ownership/metadata status, and bounded final
    names; it never exposes credentials, callback URLs, source message bodies,
    title prompts, attachment contents, or arbitrary provider payloads;
  - deterministic title fixtures match exact safe test prompts before the existing
    catch-all title fixture;
  - every product journey uses public API, signed provider HTTP, Gateway,
    interaction, OAuth/setup, or Access-Allow paths and never mutates PostgreSQL
    directly;
  - eventually consistent title and provider convergence uses bounded polling and
    stable state transitions rather than sleeps or timing-only assertions;
  - mixed-version outcomes may conservatively relinquish provider rename authority
    while Session execution and ordinary delivery remain correct.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`
- Authority references:
  `title-260802/REQ-1` through `REQ-7`;
  `title-260802/ADR-D1` through `ADR-D6`;
  `title-260802/DESIGN` revision `5`;
  current External Channel and E2E-primary Specs
- Design delta: `None`
- Removal obligations:
  - replace the Discord fake's ID-only thread state with exact bounded provider
    ownership, name, flag, relationship, and creation metadata needed by M4/M5/M8;
  - replace message-only fake barriers with bounded operation-specific provider
    barriers for provisioning and title reconciliation;
  - replace the absence of direct fake thread GET/PATCH and takeover mutation with
    the exact Phase 3 provider contract;
  - replace backend-mock-only confidence with deterministic user-facing Slack and
    Discord product journeys;
  - preserve conservative provider ownership proof and never reintroduce Resource
    label, current Agent name, incomplete metadata, or legacy delivery state as
    title authority.
- Absence verification:
  - fake contract tests prove inconsistent root flags/thread objects fail closed and
    incomplete ownership evidence cannot appear complete;
  - E2E proves zero title PATCH for pre-existing, taken-over, later-Session,
    lifecycle-revoked, or conservatively relinquished projections;
  - E2E proves manual Session text, context/Bot content, tool results, secrets, raw
    attachments, and source bodies do not appear in provider evidence or mutations;
  - repository search and diff audit prove no direct test DB writes, live-provider
    requirement, new product/configuration surface, or ordinary-delivery semantic
    change;
  - backend regression and deterministic E2E prove Session wake, AgentRun, and
    ordinary delivery never wait for provider title readiness.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Discord fake provider contract | `/root/title-testenv-owner` | `testenv/azents/e2e/src/support/discord_provider_fake.py`; `testenv/azents/e2e/src/tests/test_discord_provider_fake.py` | Phase 3 Discord direct GET/PATCH and proof fields | Rich bounded thread state, exact routes, sequences, barriers, takeover mutation, sanitized evidence | Focused fake contract Pytest; Ruff format/check; redaction assertions |
| Deterministic title fixture and product journeys | `/root/title-testenv-owner` | `testenv/azents/e2e/src/support/aimock_fixtures/agents_md_loader.json`; `testenv/azents/e2e/src/tests/azents/public/test_external_channels.py` and narrowly required test helpers | Stable fake contract and existing public API/Gateway scaffolds | P0 Discord and Slack journeys plus P1 exclusion, Access-Allow, edit, existing-thread, takeover, retry, lifecycle, and mixed-version evidence | AIMock strict-load startup; targeted public External Channel E2E; no-direct-DB-write audit |
| Integration defect remediation | `/root` | Only affected Phase 1–3 backend paths and focused tests if an E2E failure proves a product defect | Reproduced deterministic failure and approved M1–M8 contract | Minimal contract-preserving fix or explicit `None` finding | Focused backend regression, Ruff, Pyright when product code changes, affected E2E rerun |
| Plans, conformance, and final validation | `/root` | Phase plan, branch/PR metadata, cross-workstream integration and validation evidence | Stable testenv diff | Integrated Phase 4 diff, M1–M8/removal audit, final matrix, PR | Focused/full deterministic E2E, affected backend/full backend as required, docs validation, diff audit |
| Independent review | `/root/title-feature-reviewer` | Read-only complete Phase 4 diff | Stable implementation and evidence | Prioritized findings or PASS | Review against M1–M8, test authenticity, evidence safety, no-direct-DB-write rule, and Phase 5 exclusion |

- Integration order:
  1. Testenv owner replaces the fake's ID-only thread state, adds exact direct
     thread GET/PATCH, operation sequences, barriers, takeover mutation, and
     sanitized evidence with focused fake contract tests.
  2. Testenv owner adds exact deterministic title fixtures before the catch-all and
     proves strict AIMock fixture loading.
  3. Testenv owner builds P0 Discord and Slack journeys from existing Gateway,
     setup, Access-Allow, and public API scaffolds.
  4. Testenv owner adds P1 journeys in risk order: pre-existing thread, manual edit,
     human takeover, retry, lifecycle, mixed-version/Agent rename, then
     context/Bot/attachment exclusion and later-Session ineligibility.
  5. Primary orchestrator reproduces and fixes only genuine product integration
     defects, then reruns invalidated evidence.
  6. Testenv owner runs focused checks and requests read-only review from
     `/root/title-feature-reviewer`.
  7. Primary orchestrator audits scope drift and removal absence, runs the complete
     deterministic and affected backend matrix, records evidence, commits, and
     opens the stacked PR.
- Independent review:
  - Reviewer: `/root/title-feature-reviewer`.
  - Scope: complete Phase 4 diff against all Requirements, ADR D1–D6, approved
    Design revision 5 M1–M8, this execution plan, testenv conventions, and prior
    Phase 1–3 interfaces.
  - Criteria: authentic user-facing journeys without DB shortcuts, exact
    root/thread/provider evidence, bounded and secret-safe fake state, deterministic
    retry/takeover/lifecycle ordering, immediate execution independence, exact
    one-time PATCH behavior, conservative mixed-version outcomes, complete required
    scenario coverage, and Phase 5 exclusion.
  - Inputs: Requirements, ADR, approved Design revision 5, current Specs, PRs
    #1093–#1095, this plan, implementation diff, and validation evidence.
  - Output: grounded Critical/Warning findings or explicit PASS.
- Final validation:
  - `cd testenv/azents/e2e && uv run ruff format --check
    src/support/discord_provider_fake.py
    src/tests/test_discord_provider_fake.py
    src/tests/azents/public/test_external_channels.py`
  - `cd testenv/azents/e2e && uv run ruff check
    src/support/discord_provider_fake.py
    src/tests/test_discord_provider_fake.py
    src/tests/azents/public/test_external_channels.py`
  - focused Discord and Slack fake contract Pytest
  - targeted automatic-title External Channel E2E with deterministic AIMock
  - affected Phase 1–3 backend title/history/delivery/projection regressions;
    backend Pyright and full backend Pytest only when product code changes or
    integrated evidence invalidates prior shared results
  - required credential-free lane:
    `cd testenv/azents/e2e &&
    uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src`
  - `python -m pytest scripts/tests/test_gen_docs_index.py`
  - pre-commit snapshot/frontmatter/index validation during commit
  - direct-DB-write, secret-evidence, forbidden-surface, and production contract
    audits
  - `git diff --check`
- Scope-drift check:
  - verify every Phase 4 journey and fake removal obligation is represented by
    deterministic evidence;
  - verify no fake convenience weakens exact provider proof, fail-closed
    classification, or takeover preservation;
  - verify Session execution, ordinary delivery, and Slack behavior remain
    independent from Discord projection readiness;
  - verify no material product behavior, new runtime/configuration surface,
    direct-DB-write shortcut, live-provider dependency, Spec promotion,
    implementation marking, or plan cleanup is added;
  - return any new material mechanism to feature design.
- Context checkpoint:
  - Phase 3 already provides exact Discord root reading, direct thread GET/PATCH,
    GET-before-PATCH reconciliation, provider takeover, retry, and restrictive
    lifecycle contracts with complete lower-level tests.
  - Discovery found no known backend contract gap. Phase 4 starts as test-only and
    treats E2E failures as integration evidence rather than weakening the fake.
  - The current fake lacks rich thread state, direct thread GET/PATCH, generic
    provider barriers, takeover mutation, final-name evidence, and exact External
    Channel title fixtures.
  - Existing Discord Gateway setup and Slack approval journeys provide the
    user-facing scaffolds; tests must extend those paths without direct database
    mutation.
  - Full deterministic evidence may accept conservative mixed-version
    relinquishment, but never unsafe adoption or provider mutation.
  - Phase 5 still owns Living Spec promotion, matching implementation dates, and
    removal of all feature plans. Design delta: `None`.
