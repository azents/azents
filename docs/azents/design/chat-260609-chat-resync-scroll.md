---
title: "Chat Idle Return Resync Reinforcement Design"
created: 2026-06-10
updated: 2026-06-10
tags: [frontend, chat, reliability, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: chat-260609
migration_source: "docs/azents/design/chat-idle-resume-resync.md"
historical_reconstruction: true
---

# Chat Idle Return Resync Reinforcement Design

## Overview

Chat screen uses WebSocket live events together with REST history/live baseline. Existing Chat session resync design introduced structure that applies REST baseline after `subscribed` ack and performs periodic health check while visible. However, when returning from browser idle states such as mobile browser app background, another tab, or PC sleep, `visibilitychange` alone cannot reliably detect return.

This design extends signals for detecting browser idle return and defines FE reinforcement that converges through subscription health check and REST baseline instead of directly trusting WebSocket state on return. It also fixes a bug where “new messages” chip appears merely because user scrolled up to start browsing middle history.

Base decision remains [chat-260609/ADR](../adr/chat-260609-chat-resync-scroll.md). [chat-260609/ADR](../adr/chat-260609-chat-resync-scroll.md) is an implemented decision log, so do not modify it. This document is implementation reinforcement design for that decision; after completion, current behavior is promoted to `spec/flow/chat-session-resync.md`.

## Problem

### Missing mobile/browser idle return

In these states, even if page is open, we cannot assume JS event loop and WebSocket delivery were processed normally.

- Mobile browser app was backgrounded or suspended and then returned.
- User stayed in another tab or app and then returned to current tab.
- Same page instance remains alive after PC sleep and return.
- Network disconnected and recovered.
- Browser restores existing page instance from page cache.

At this time, browser WebSocket object can temporarily look `OPEN`, but actual session subscription can be stale. Therefore, if chat screen considers itself latest based only on `readyState` or `visibilitychange`, live events can be lost or stale screen can remain.

### Incorrect new messages chip display

Currently, when switching to middle history browsing, detached state's `hasNewer` is always set to true. Because of this, even when session is stopped and no new message exists, “new messages” chip appears if user scrolls up and loads older history.

Detached history browsing means “not looking at latest tail,” which differs from fact that “new messages exist.” These two states must be separated.

## Goals

- Detect browser idle return with multiple lifecycle signals and timer drift.
- On return, do not trust WebSocket `OPEN`; perform subscription health check.
- If health check succeeds, re-fetch REST baseline and replay buffered live events.
- If health check fails, switch to ticket refresh/reconnect path.
- Separate detached state entry from “new messages exist” display.
- Do not display “new messages” chip from simple older history load alone.

## Non-goals

- Introduce Service Worker or Push-based background delivery.
- Change server WebSocket protocol.
- Introduce virtual scroll/viewport virtualization.
- Solve long detached buffer memory pressure.
- Modify [chat-260609/ADR](../adr/chat-260609-chat-resync-scroll.md) body.

## Requirements

| ID | Content | Basis |
| --- | --- | --- |
| REQ-1 | Chat FE treats `visibilitychange` to visible, `focus`, `pageshow`, `online`, and timer drift as idle return candidate signals. | Browser idle return detection reinforcement |
| REQ-2 | Idle return candidate signals are merged into one resume resync function, with duplicate execution controlled by throttle/in-flight guard. | Prevent duplicate event burst |
| REQ-3 | Resume resync enables live event buffering first, then performs subscription health check. | Prevent event interleaving during REST baseline apply |
| REQ-4 | When health check ack arrives, execute REST baseline refetch path. | [chat-260609/ADR-D4](../adr/chat-260609-chat-resync-scroll.md) extension |
| REQ-5 | If health check ack fails or times out, switch to ticket refresh/reconnect path. | [chat-260609/ADR-D4](../adr/chat-260609-chat-resync-scroll.md) |
| REQ-6 | If timer drift exceeds threshold, treat it as return from sleep/suspend and request resume resync. | Compensate for missing visibilitychange |
| REQ-7 | Do not force `hasNewer` to true when entering detached by older history load from `LATEST_FOLLOWING`. | Prevent chip misdisplay |
| REQ-8 | “New messages” chip is shown only in detached state when actual newer-direction gap or live/newer event is confirmed. | Separate state semantics |

## Decision Table

| Decision | Implementation requirements |
| --- | --- |
| Browser idle return is judged by composite resume signal, not single event. | REQ-1, REQ-2, REQ-6 |
| On resume, prioritize application-level subscription health check over WebSocket object state. | REQ-3, REQ-4, REQ-5 |
| Detached entry and newer existence are independent states. | REQ-7, REQ-8 |

## Frontend Design

### Resume signal

`useChatWebSocket` treats these signals as resume candidates.

- `document.visibilitychange` transition to `visible`.
- `window.focus`.
- `window.pageshow`.
- `window.online`.
- Drift exceeding threshold in periodic timer based on `Date.now()`.

Each signal does not call REST directly and enters common resume resync function. Common function has these guards.

- no-op if session id and WebSocket URL are absent.
- no-op if resume resync is already in progress.
- no-op if inside short throttle window since previous resume resync.

### Resume resync sequence

1. Turn on live event buffering and clear existing buffer.
2. Send `subscription_health_check`.
3. If ack arrives, call existing batch reload callback to fetch REST baseline again.
4. If ack fails or times out, transition to reconnect state and call auth/ticket refresh callback.
5. After REST baseline applies, existing replay path applies buffered live events.

This flow uses same convergence point as existing baseline application flow after `onSubscribed`.

### Timer drift

Timer drift is defined as gap sufficiently longer than expected `setInterval` tick interval. For example, if gap of 30 seconds or more occurs on 10-second probe, consider it return after sleep or browser suspend. This value is conservative, prioritizing avoidance of excessive reload over real-time behavior.

### New message chip

`useChatSessionContainer.onLoadMore` can transition to detached state while prepending older history. This transition means user moved away from latest tail, not that new events exist in newer direction.

Therefore, when entering detached, `hasNewer` starts as false. It turns true later only when `has_newer` from `after` pagination result, detached state batch/live resync result, or held live event actually confirms newer gap.

## Implementation Targets

- `typescript/apps/azents-web/src/features/chat/hooks/useChatWebSocket.ts`
  - Add composite resume detector.
  - Add resume resync throttle/in-flight guard.
  - Add timer drift probe.
- `typescript/apps/azents-web/src/features/chat/containers/useChatSessionContainer.ts`
  - Remove forced `hasNewer=true` when entering detached from older history load.
  - While keeping detached state, reflect newer existence only from server `has_newer` or live/resync path.

## Verification Strategy

### TypeScript Static Verification

- `cd typescript && corepack pnpm --filter @azents/web typecheck`
- `cd typescript && corepack pnpm --filter @azents/web lint`

### Manual/E2E-centered Scenarios

| ID | Scenario | Expected result |
| --- | --- | --- |
| TC-1 | Open chat screen on mobile, background browser app, then return. | resume resync runs and screen converges to latest state through REST baseline. |
| TC-2 | Open chat screen on PC, sleep, then return. | resume resync runs through timer drift. |
| TC-3 | Move to another tab/app and return focus. | baseline reload runs after subscription health check. |
| TC-4 | Network goes offline and recovers online. | resume resync or reconnect path runs. |
| TC-5 | Session is stopped and there are no new messages; scroll up to load older history. | “new messages” chip does not appear. |
| TC-6 | Actual new live event or newer history appears while detached. | “new messages” chip or latest reset entry point appears. |

### Spec Promotion

After implementation completes, update `docs/azents/spec/flow/chat-session-resync.md`.

- Add list of idle return detection signals.
- Add resume resync sequence.
- Reinforce new message chip invariant.
- Update `last_verified_at`.
- Add v2 changelog entry.

## Risks and Mitigations

- `focus`, `pageshow`, and `visibilitychange` can occur consecutively in short time. Reduce duplicate reloads with throttle and in-flight guard.
- Timer drift can have false positives. REST baseline reload is safe convergence behavior, so prioritize correctness.
- On health check failure, ticket refresh may occur even when reconnect is not needed. Reuse existing reconnect/auth refresh path, limiting user impact to connection status display.
- Narrower chip display condition can delay actual new event display. Mitigate by preserving newer gap reflection from batch/live resync results.
