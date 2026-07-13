---
title: "Chat Timeline Reliability Hardening Validation Report"
created: 2026-07-13
tags: [backend, frontend, chat, reliability, testing]
---

# Chat Timeline Reliability Hardening Validation Report

## Scope

This report validates the implementation stack described by [Chat Timeline Reliability Hardening](./chat-timeline-reliability-hardening.md) and its temporary implementation plan through PR 9 of 11.

The validation focuses on:

- canonical WebSocket delivery and the confirmed subscription barrier;
- durable REST history convergence and bidirectional raw cursors;
- consecutive reasoning output identity;
- immutable requested inference intent, including explicit nullable effort;
- detached/latest action and follow behavior represented by frontend stories;
- backend projection, publication, pagination, and live-state boundaries;
- build and static quality of the complete stacked implementation.

## Environment

| Item | Value |
| --- | --- |
| Runtime | Linux 6.8.0-134-generic x86_64 |
| Python | 3.14.6 |
| uv | 0.11.1 |
| Node.js | 24.18.0 |
| pnpm | 11.1.0 |
| Docker | Unavailable: `/bin/sh: docker: not found` |

The local runtime cannot start the containerized Azents E2E topology. Deterministic E2E execution is therefore delegated to the GitHub Actions `ci-python-e2e-run` job, which provisions Docker Buildx before running `uv run pytest`. No local E2E pass is claimed.

## Added Validation

### Cross-layer deterministic E2E

`test_agent_execution_persistence.py::test_canonical_ws_history_pagination_and_intent_converge` now performs one public-path scenario without direct database access:

1. creates a workspace, integration, Agent, and team-primary session through public APIs;
2. connects through the public Chat WebSocket and waits for `subscribed`;
3. verifies `subscription_health_check_ack` on the confirmed connection;
4. submits two deterministic turns with distinct reasoning summaries;
5. accepts only canonical WebSocket action envelopes and rejects raw top-level durable event frames;
6. verifies each durable append ID is delivered once per observed turn;
7. compares WebSocket delivery with authoritative REST history;
8. verifies both user rows preserve `{model_target_label: "default", reasoning_effort: null}`;
9. verifies both reasoning summaries survive as distinct durable events;
10. walks every raw history page backward with `next_cursor`, then verifies forward paging with `previous_cursor`, `has_more`, and `has_newer`.

The AIMock fixture adds deterministic two-turn reasoning output for this scenario.

### Frontend interaction coverage

`ChatView.stories.tsx::DetachedLatestResetIsKeyboardAccessible` renders a detached timeline with a confirmed newer gap, locates the semantic `New message` button by accessible role/name, activates it with Enter, and verifies that latest reset is requested. The story compiles in the production Storybook build. The repository does not currently expose a headless Storybook interaction-test command, so local execution evidence is limited to story compilation rather than a browser test run.

## Local Results

| Area | Command | Result |
| --- | --- | --- |
| Testenv lint | `cd testenv/azents/e2e && uv run ruff check .` | Pass |
| Testenv format | `cd testenv/azents/e2e && uv run ruff format --check .` | Pass; 37 files formatted |
| Testenv types | `cd testenv/azents/e2e && uv run pyright .` | Pass; 0 errors |
| Backend lint | `cd python/apps/azents && uv run ruff check .` | Pass |
| Backend types | `cd python/apps/azents && uv run pyright` | Pass; 0 errors |
| Backend focused tests | `uv run pytest src/azents/repos/message/repository_test.py src/azents/api/public/chat/v1/chat_api_test.py src/azents/worker/events/publisher_test.py src/azents/worker/live/event_projector_test.py src/azents/worker/worker_test.py` | Pass; 77 passed, 2 skipped |
| Web lint | `cd typescript && pnpm run lint --filter=@azents/web` | Pass |
| Web types | `cd typescript && pnpm run typecheck --filter=@azents/web` | Pass |
| Web production build | `cd typescript && pnpm run build --filter=@azents/web` | Pass |
| Storybook build | `cd typescript && pnpm --filter @azents/web build-storybook` | Pass |
| Fixture syntax | `python -m json.tool testenv/azents/e2e/src/support/aimock_fixtures/agents_md_loader.json` | Pass |
| Patch integrity | `git diff --check` | Pass |
| Deterministic E2E | `cd testenv/azents/e2e && uv run pytest` | Deferred to CI because Docker is unavailable locally |

The two focused backend skips are the PostgreSQL-backed repository cases that require the unavailable local container runtime. Their test code remains part of deterministic CI.

## Primary Validation Matrix

| ID | Behavior | Evidence | Status |
| --- | --- | --- | --- |
| E2E-1 | Failed initial/latest REST sync does not trap buffered observations | Finite resync implementation review plus web type/build validation; full browser fault injection requires a browser E2E harness not currently present in the repository | Implementation validated; browser automation gap recorded |
| E2E-2 | Detached history remains stable while newer observations arrive | Detached-state selector and resync implementation review; `DetachedLatestResetIsKeyboardAccessible` covers the confirmed-newer reset control | Implementation validated; browser streaming automation gap recorded |
| E2E-3 | Consecutive reasoning turns remain distinct | New deterministic AIMock reasoning fixture and canonical WS/REST convergence E2E | Automated in deterministic CI |
| E2E-4 | Provider result text/attachments survive projection | Backend normalizer/projector tests and existing public file-upload E2E cover transport-safe attachments | Existing automated coverage |
| E2E-5 | Tool call/result survives raw page boundaries | Raw cursor traversal in the new E2E plus backend pagination and event projection tests | Automated across backend and deterministic CI |
| E2E-6 | Live internal-agent messages promote without disappearing | Existing subagent E2E plus client event identity/promotion implementation review | Existing automated coverage |
| E2E-7 | Terminal worktree action remains durable in detached history | Existing worktree lifecycle E2E and durable `action_execution_result` projection tests/stories | Existing automated coverage |
| E2E-8 | Explicit user intent leaves follow during streaming | Scroll/follow implementation review and successful web/Storybook builds | Browser automation gap recorded |
| E2E-9 | Requested target and nullable effort remain historical | New canonical WS/REST convergence E2E asserts explicit `reasoning_effort: null`; existing per-prompt profile E2E covers distinct labels/efforts | Automated in deterministic CI |

The browser-only gaps are test-harness gaps rather than known product defects. No production-only fault switch or custom browser relay was added in this validation PR.

## Implementation-to-Spec Comparison

| Contract | Implementation result | Current Living Spec | PR 10 action |
| --- | --- | --- | --- |
| Projection/publication failures do not fail durable run or REST commit boundaries | Implemented by isolated best-effort projection boundaries while preserving essential broker wake-up and cancellation semantics | Not stated comprehensively in `agent-execution-loop.md` | Add the non-fatal projection boundary and ordering rules |
| Public Chat WebSocket carries canonical actions after a confirmed subscribe barrier | Implemented and exercised by the new E2E | `chat-session-resync.md` is substantially aligned | Clarify that raw durable Event frames are not a public frame type and record confirmation-generation semantics |
| Resync is one finite transaction with fresh REST results and guaranteed buffer release | Implemented for initial, resume, periodic, reconnect, and latest-reset paths | Current spec describes the flow but not all epoch/supersession and failure-finalization invariants | Add finite transaction, fresh-baseline, supersession, malformed-frame, and guaranteed-release rules |
| Detached history ignores live mutation and only records confirmed newer availability | Implemented | Current spec is substantially aligned | Tighten durable/live observation and latest-reset wording |
| Raw pages own cursors and render selectors merge across page boundaries | Implemented, including render-hidden page advancement | Cursor direction is documented; raw cursor ownership and selector identity are incomplete | Add raw page/cursor and cross-page projection identity rules |
| Reasoning, assistant, provider result, and internal-agent identities survive live-to-durable promotion | Implemented | Event taxonomy exists, but provider result rendering and promotion identity are incomplete | Add output identity, provider status/output/attachment, and promotion precedence rules |
| Terminal action results are durable while nonterminal progress remains live-only | Implemented | Current specs are aligned | Verify code paths and refresh `last_verified_at` |
| Human input preserves immutable requested intent separately from applied provenance | Implemented and exercised with explicit nullable effort | `conversation.md` and `chat-session-resync.md` mostly align; `agent-execution-loop.md` still contains stale wording that a canonical user row stores applied profile data | Remove stale applied-profile wording and define requested/applied boundaries consistently |
| Follow uses one 48px bottom/bounce boundary, explicit intent cancels automatic pinning, and underfilled history auto-loads | Implemented | General follow behavior is documented, but the exact boundary, saved detached restoration, intent override, and viewport-fill loop are missing | Add exact follow, restoration, auto-fill, and accessibility contracts |

## Findings

- No new implementation defect was found by local static checks, focused backend tests, frontend builds, or the validation review.
- The validation E2E intentionally uses only public API and WebSocket paths; it does not seed or mutate product tables directly.
- Docker-dependent deterministic E2E remains the required CI gate for this PR.
- Living Spec drift is bounded to the items listed above and is assigned to PR 10. Implemented ADRs remain unchanged.
