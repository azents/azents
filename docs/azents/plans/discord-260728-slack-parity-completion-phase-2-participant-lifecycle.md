---
title: "Discord Slack Parity Completion Phase 2 Execution Plan"
created: 2026-07-28
tags: [discord, slack, external-channel, participant, work, lifecycle]
---

# Phase Execution Plan

- Phase: `2 — Participant, work, and lifecycle completion`
- Branch/base:
  `fix/discord-parity-participant-lifecycle` →
  `fix/discord-parity-delivery-activation`
- PR boundary: Complete Discord participant invocation, selector and authorization,
  thread-scoped work/reply/file delivery, progress recovery, and canonical lifecycle
  cleanup with deterministic participant and lifecycle evidence.
- Inputs:
  - merged `discord-260728` Requirements, ADR, and Design;
  - the multi-phase completion plan and checklist from PR #984;
  - Phase 1 provider-delivery, hydration, activation, and wake ordering from PR #985;
  - current External Channel domain, authorization, delivery, ingress, lifecycle, and
    E2E strategy specs as behavior references pending the later spec-promotion phase.
- Deliverables:
  - mention and Guild Message Command source entry converge on one immutable binding;
  - selector pagination, navigation, selection, immediate access, and approval-required
    access preserve complete route catalog and signed interaction scope;
  - allow, deny, block, revocation, and repeated decisions preserve provider-neutral
    authorization, exactly-once release, and immutable binding behavior;
  - approval controls, Session navigation, progress, replies, continuations, files,
    recovery, and cleanup target one canonical Discord thread;
  - Discord progress projection parts support stable create, update, page growth,
    reduction, final-reply cleanup, and confirmed-missing-page recovery;
  - Runtime and Exchange files retain current authority, streaming validation, and
    redaction boundaries;
  - archive, disconnect, Agent decommission, credential failure, permission failure,
    reconnect-required, and provider cleanup preserve canonical terminal state,
    generation/lease fences, and durable failed or unknown evidence;
  - deterministic participant and lifecycle E2E prove the complete provider-visible
    journey without exposing provider content or capabilities.
- Non-goals:
  - Discord Workspace administration UI, provider deep-link restoration, combined
    connection pagination, stories, or browser E2E;
  - integrated all-lane validation and completion-checklist closure;
  - living-spec promotion or Requirements/Design implementation dates;
  - plan cleanup, deployment, production mutation, or historical ambiguous-write retry;
  - backward compatibility or fallback behavior not required by the current contract.
- Interfaces:
  - resource labels remain the canonical source, parent, root, existing-thread, and
    delivery-thread identity; every provider-visible participant output uses the
    resolved delivery thread;
  - selector scope remains bound to connection, resource, admission, principal, actor,
    page, and configuration generation; transient interaction tokens and selected
    values are never persisted;
  - access decisions remain provider-neutral and block retains precedence over grants
    and automatic access;
  - Discord progress state is derived from ordered work projection parts for the
    current work cycle; Slack legacy progress-message state is not authoritative;
  - a delivered final reply may enable progress cleanup, while failed or unknown reply
    or cleanup mutations retain durable evidence and are not replayed blindly;
  - only confirmed missing/deleted active progress pages may be recreated; ambiguous
    provider mutations are never retried;
  - file delivery uses current Runtime or Exchange authority and bounded streaming;
    evidence excludes locators, URLs, bytes, names when sensitive, and provider bodies;
  - lifecycle transitions commit canonical terminal state before provider cleanup and
    never roll canonical state back because cleanup failed.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Backend participant and lifecycle | `/root/parity-backend-owner` | Discord interaction/source/selector, event processor/access, channel action/delivery, work, file, lifecycle, repository paths and focused tests under `python/apps/azents/` | Phase 1 activation and provider-delivery contracts | Complete participant, work, recovery, and lifecycle behavior without weakening authorization or durability fences | Focused Ruff, full backend Pyright, interaction/selector/access/work/action/file/lifecycle tests |
| Deterministic participant and lifecycle evidence | `/root/parity-testenv-owner` | `testenv/azents/e2e/src/support/discord_provider_fake.py`, fake contract tests, and Phase-2-specific Discord public E2E | Stable backend interaction, delivery, recovery, and lifecycle contracts | Safe deterministic mention/command, selector/approval, reply/file/progress/recovery/lifecycle evidence | Testenv Ruff/Pyright, fake suite, focused participant and lifecycle E2E |
| Integration and plans | `/root` | Phase plan, completion checklist, shared integration files, branch/PR metadata | Both implementation workstreams | Integrated scope, validation ledger, stacked PR | Scope diff, combined validation, commit hooks |
| Independent review | `/root/parity-reviewer` | Read-only complete Phase 2 diff | Completed implementation and validation reports | Requirements, authorization, data-loss, lifecycle, and interface findings | Full review report; targeted re-review only when required |

- Integration order:
  1. Backend owner audits existing Discord selector, source, progress, file, recovery, and
     lifecycle behavior against this fixed interface and implements only missing Phase 2
     wiring and focused regressions.
  2. Testenv owner extends the fake and participant/lifecycle E2E against stable backend
     contracts; fixture-only additions may proceed in parallel when paths do not
     overlap backend ownership.
  3. Backend behavior needed by E2E is integrated before final participant and
     lifecycle journey execution.
  4. Each participating owner runs its focused validation and requests read-only review
     from `/root/parity-reviewer`.
  5. Required findings are corrected in one pass, affected validation is rerun, and
     targeted re-review is requested only for requirements, authorization, data-loss,
     lifecycle, or material interface corrections.
  6. The primary agent performs the final scope audit, combined validation, commit, and
     stacked PR creation before Phase 3 begins.
- Independent review:
  - Scope: the complete Phase 2 diff against `discord-260728/REQ-1` through `REQ-5`,
    `REQ-7`, `REQ-8`, the accepted ADR, Design P0/P1 and lifecycle sections, current
    specs, and this phase contract.
  - Criteria: immutable binding and principal provenance, signed selector scope,
    block/grant precedence, exactly-once context release, one canonical thread,
    current-work projection-part authority, no ambiguous mutation replay, reply-gated
    cleanup, confirmed-only recovery, file authority, terminal-state-before-cleanup,
    generation/lease fences, and safe deterministic evidence.
  - Inputs: Requirements, ADR, Design, multi-phase plan, this execution plan,
    implementation diff, focused results, and deterministic E2E results.
  - Output: grounded Critical/Warning findings or explicit no findings.
- Final validation:
  - changed backend and testenv Ruff format/check;
  - full backend and testenv E2E Pyright;
  - focused Discord interaction, source, selector, access, event processor, work,
    channel action, delivery, file, lifecycle, and repository tests;
  - Discord fake contract suite;
  - deterministic participant E2E for mention or Message Command through selection or
    approval, activation, reply, progress, file, completion cleanup, and continuation;
  - deterministic recovery E2E for confirmed deleted progress;
  - deterministic lifecycle E2E for disconnect/reconnect-required/archive/decommission;
  - full backend pytest when the integrated backend diff is final;
  - `git diff --check` and commit hooks.
- Scope-drift check:
  Compare the final diff with the deliverables and non-goals above. Move Workspace UI,
  browser evidence, combined pagination/deep-link work, integrated all-lane QA, spec
  promotion, cleanup, deployment, and live-provider verification to their planned later
  phases unless a minimal prerequisite is required for Phase 2 correctness.
