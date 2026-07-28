---
title: "Discord Slack Parity Completion Phase 1 Execution Plan"
created: 2026-07-28
updated: 2026-07-28
tags: [discord, slack, external-channel, delivery, hydration, activation]
---

# Phase Execution Plan

- Phase: `1 — Delivery diagnostics and activation ordering`
- Branch/base:
  `fix/discord-parity-delivery-activation` →
  `fix/discord-slack-parity-completion`
- PR boundary: Correct Discord provider delivery diagnostics, thread convergence,
  hydration-fenced binding activation, provider-dispatched initial control/progress
  delivery, and the pre-wake delivery gate.
- Inputs:
  - merged `discord-260728` Requirements, ADR, and Design;
  - completion checklist and multi-phase implementation plan from PR #984;
  - read-only backend, testenv, web, and independent-review discovery.
- Deliverables:
  - safe Discord unknown-result categories without replaying ambiguous writes;
  - deterministic root-thread create/reuse convergence;
  - every new Discord binding starts `waiting_hydration`;
  - mention, selected-admission, and approval Allow paths use the same hydration gate;
  - no initial batch, mailbox item, work release, or wake before hydration and
    correlated-event completion;
  - root-thread Session link and checking progress are both delivered before wake;
  - failed or unknown required initial delivery leaves the binding waiting and keeps
    durable evidence;
  - focused and deterministic fixture tests for the corrected ordering and outcomes.
- Non-goals:
  - full selector/approval decision E2E;
  - complete progress-page lifecycle recovery and lifecycle cleanup;
  - Workspace UI and browser E2E;
  - current living-spec promotion;
  - retrying or mutating historical production delivery rows;
  - deployment or live provider mutation.
- Interfaces:
  - `DiscordDeliveryResult.status` remains `delivered`, `failed`, or `unknown`.
  - `error_kind` distinguishes safe unknown categories while provider response bodies,
    credentials, exception details, message contents, and transient capabilities remain
    absent.
  - Discord message writes retain deterministic nonce and one-attempt semantics.
  - Thread create ambiguity is reconciled with provider reads; the mutating request is
    never blindly replayed.
  - Provider-native one-thread-per-root behavior plus post-mutation read reconciliation
    must converge concurrent initial deliveries on one canonical resource label.
  - `waiting_hydration` remains the durable pre-activation state through history,
    correlated-event, and required initial-delivery gates.
  - Required initial delivery is satisfied only when the Session-link control and every
    initial checking-progress part are `delivered`.
  - A `failed` or `unknown` required initial attempt does not wake the Session or mark
    the binding active.
  - Retry of the binding reconciler reuses existing invocation, mailbox, work,
    delivery, and provider identities and performs no second provider mutation for a
    terminal attempt.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Backend provider and activation | `/root/parity-backend-owner` | `python/apps/azents/src/azents/services/external_channel/{discord_delivery.py,channel_action.py,event_processor.py,access.py}`; required repository/work paths and focused tests | Fixed interfaces above | Correct result classification, thread convergence, waiting activation, provider-dispatched initial delivery, delivered-before-wake gate | Focused Ruff, Pyright, Discord delivery/event/access tests |
| Deterministic provider fixture | `/root/parity-testenv-owner` | `testenv/azents/e2e/src/support/discord_provider_fake.py`, `testenv/azents/e2e/src/tests/test_discord_provider_fake.py`, Phase-1-specific Discord E2E additions | Backend request/response and evidence contract | History pages, root/thread evidence, one-shot failure categories, safe operation ordering evidence | Fake contract tests and focused Discord E2E |
| Integration and plans | `/root` | phase plan, completion checklist, shared integration files, branch/PR metadata | Both implementation workstreams | Integrated diff, checklist evidence, final validation | Scope diff, combined focused checks |
| Independent review | `/root/parity-reviewer` | Read-only complete Phase 1 diff | Completed implementation and validation reports | Requirements/security/data-loss/interface findings | Review report; targeted re-review only if required |

- Integration order:
  1. Backend owner fixes safe result categories and the provider-dispatched activation
     state machine.
  2. Testenv owner implements the fixed Discord REST/history/evidence contract in
     parallel without product-state database writes.
  3. Backend and testenv focused tests establish delivery and ordering behavior.
  4. Primary orchestrator integrates shared changes and runs combined validation.
  5. Each implementation owner requests read-only review from
     `/root/parity-reviewer`.
  6. Required findings are corrected in one pass, followed by affected validation and
     targeted re-review when the finding changes requirements, security, data-loss, or
     a material interface.
- Independent review:
  - Scope: complete Phase 1 diff against `discord-260728/REQ-3`, `REQ-4`, `REQ-5`,
    `REQ-7`, the accepted ADR, current specs, and this phase contract.
  - Criteria: no hydration bypass, no wake before required provider-visible setup,
    exactly-once release, no ambiguous write replay, safe redaction, deterministic
    thread convergence, preserved lock/generation/lease fences, and no Slack
    regression.
  - Inputs: Requirements, ADR, Design, completion plan, this execution plan,
    implementation diff, and validation results.
  - Output: grounded Critical/Warning findings or explicit no findings.
- Final validation:
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - `cd python/apps/azents && uv run pyright`
  - focused Discord delivery, event processor, access, work, and repository tests
  - `cd testenv/azents/e2e && uv run pytest -q src/tests/test_discord_provider_fake.py`
  - focused Phase 1 Discord E2E through the deterministic fake
  - `git diff --check`
- Validation evidence:
  - changed backend and testenv Ruff format/check passed;
  - full backend and testenv E2E Pyright passed with zero errors and warnings;
  - full backend pytest passed: `3461 passed`, `12 warnings`, `0 failed`;
  - focused Discord history and event processor validation passed:
    `55 passed`;
  - migration validation passed: `10 passed`;
  - Python public-client activation-status contract passed: `1 passed`;
  - TypeScript public-client generation and typecheck passed;
  - Discord provider fake contract suite passed: `23 passed`;
  - deterministic activation journey passed: `1 passed`, `9 deselected`;
  - the provider barrier proved one completed initial message while the binding
    remained `waiting_hydration` and the Session remained idle, followed by both
    required initial messages, `active`, and a public execution effect after release;
  - final independent review reported no remaining Critical or Warning findings.
- Scope-drift check:
  Compare the final diff against the deliverables and non-goals above. Move selector
  lifecycle completion, projection-part lifecycle cleanup, full participant E2E,
  Workspace UI, browser E2E, spec promotion, and cleanup work to their planned later
  phases unless a small prerequisite is required to keep the Phase 1 contract
  internally correct.
