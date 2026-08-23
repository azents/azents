---
title: "Consistent TurnAction Capabilities Implementation Plan"
created: 2026-08-23
tags: [agent, chat, backend, implementation]
---

# Consistent TurnAction Capabilities Implementation Plan

- Requirements: [action-260823/REQ](../requirements/action-260823-consistent-turn-actions.md)
- ADR: [action-260823/ADR](../adr/action-260823-consistent-turn-actions.md)
- Design: [action-260823/DESIGN](../design/action-260823-consistent-turn-actions.md), revision 1
- Approved mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`
- Design delta: None
- Delivery shape: one focused PR because the shared policy, mailbox preparation,
  and Worker executor boundaries must activate together while preserving one
  persisted action contract.
- Owner: primary agent
- Independent reviewer: `/root/reviewer-turn-action-1393`, using the
  `/code-review` workflow for a read-only review against the approved snapshot,
  current Specs, phase contract, and stable final diff.

## Phase

1. Introduce the closed capability registry, replace duplicated API/mailbox/Worker
   action selection, preserve current contracts and durable outcomes, add focused
   completeness and behavior tests, synchronize Living Specs, validate, and open
   one PR.

## Interfaces and integration boundaries

- Existing typed `ChatAction`, `PersistedChatAction`, and `TurnAction` payload
  discriminators remain unchanged.
- Public REST request/response and action catalog response schemas remain
  unchanged.
- Mailbox preparation continues to own transaction orchestration, event append,
  Run association, source deletion, and operation claim creation.
- Goal and Skill capabilities own state access and semantic preparation results.
- `RunExecutor` retains operation admission, owner-generation fencing,
  cancellation, broadcast, and result aggregation; the Worker registry owns typed
  operation dispatch.

## Removal obligations

- Remove Goal, cleanup, and Skill definition construction from the generic chat
  route.
- Remove action-specific public TurnAction admission matches from the chat route.
- Remove Goal/Skill state construction and preparation behavior from
  `MailboxService`.
- Remove action-specific operation dispatch from `RunExecutor`.
- Preserve public schemas, persisted action payloads, and durable event shapes.

## Validation

- Focused registry, mailbox, chat API, and RunExecutor pytest coverage.
- Ruff format/check and configured `ty` validation for `python/apps/azents`.
- Applicable backend test suite and documentation validation.
- `/spec-review` and required Living Spec updates.
- Stable-diff `/code-review`, followed by affected validation reruns.
- OpenAPI diff and migration absence verification; generated clients remain
  unchanged unless the source schema unexpectedly differs.

## Prerequisites, rollout, and blockers

- Reuse existing deterministic Goal, Skill projection, VFS, mailbox, and
  worktree execution fixtures; no external credentials are required.
- Existing required E2E CI provides public chat and worktree behavior evidence.
- Rollout and rollback are code-only; there is no database migration or live
  infrastructure action.
- No known blocker.

## Plan cleanup

Remove this plan and the phase execution plan only after implementation,
validation, Living Spec promotion, and PR delivery are complete.
