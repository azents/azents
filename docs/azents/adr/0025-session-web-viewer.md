---
title: "ADR-0025: Session Web Viewer Discussion — View Discord/Slack Sessions in Web UI"
created: 2026-04-16
tags: [backend, engine, frontend, api]
---

> 📌 **Related design document**: [session-web-viewer.md](../design/session-web-viewer.md)
>
> This document records design-stage discussion. See the linked document for the final design and implementation state.

# ADR-0025: Session Web Viewer — View Discord/Slack Sessions in Web UI

## Overview

This feature lets users view sessions running in Discord/Slack from the Web UI. Discord/Slack UI limitations make it frustrating because users cannot see tool call details, subagent state, and similar execution details (#2626).

This document is the output of Phase 1-1.5 from the autonomous `feature-design` skill.

---

## Current State Summary

### Event Delivery Path

`dispatch_event()` in `engine.py` sends events through only **one path** depending on adapter:

- Discord session → `DiscordAdapter.handle_event()` → Discord REST API
- Slack session → `SlackAdapter.handle_event()` → Slack SDK
- Web session → `WebAdapter.handle_event()` → `WebSocketBroadcast` → Redis Pub/Sub → WebSocket → browser

Discord/Slack session events are not published to the WebSocket channel, so real-time streaming is not possible in Web UI.

### Existing Infrastructure

- `WebSocketBroadcast`, Redis Pub/Sub based, in `broker/broadcast.py`.
- WebSocket endpoints: `/chat/v1/sessions/{id}`, `/chat/v1/sessions/new`.
- Event serialization/deserialization in `broker/serialization.py`.
- Frontend chat UI with streaming, tool call, and subagent display.
- `useSubagentSession` hook as read-only session viewer pattern.
- REST APIs for session list and message history.

---

## Discussion Points and Decisions

### D1. Where to dual-publish events

**Background**: Discord/Slack session events must also be delivered through WebSocket. Where should dual publishing happen?

**Options**:

- **A**. Handle centrally in `dispatch_event()` — after adapter call, additionally publish broadcast when adapter is not WebAdapter.
- **B**. Handle inside each adapter — DiscordAdapter and SlackAdapter publish broadcast directly inside `handle_event()`.
- **C**. Decorator/Wrapper adapter — create `BroadcastingAdapter` that wraps existing adapters and intercepts events.

**Decision: A**

- Single change point: only `dispatch_event`.
- No changes needed in individual adapters, keeping their responsibility boundaries intact.
- Broadcast failure does not affect platform delivery, because adapter call happens first and broadcast is best-effort.
- C is over-abstracted; there are only three adapters today and the pattern is simple.

### D2. Access permission model

**Background**: Current session access is limited by `conv.user_id == current_user.user_id`. The owner of a Discord/Slack session is the user who started it. Should other workspace members also be able to view it?

**Options**:

- **A**. Only own sessions, same as current behavior — keep `user_id` match check.
- **B**. All workspace members — add `workspace_id` membership check for session access.

**Decision: A**

- Simple implementation, no change to existing access-control logic.
- Since the user who mentions the bot in Discord/Slack becomes owner, that user can view the session they started.
- B adds privacy concerns and permission-model complexity, such as separate read-only permission.
- Team visibility can be added later as a separate issue if needed.

### D3. Read-only vs bidirectional

**Background**: When viewing a Discord/Slack session in Web UI, should users also be able to send messages?

**Options**:

- **A**. Read-only — disable message input; only real-time streaming + history lookup.
- **B**. Bidirectional — messages sent from Web are also delivered to the Discord/Slack session.

**Decision: A**

- The issue scope is "viewing," specifically because Discord/Slack cannot show tool call details or subagent state well.
- B is complex: how to display Web messages in Discord/Slack, avoid confusion about message origin, and handle interface conflicts.
- If users want to send messages from Web, they can start a new Web session with the same agent.
- Bidirectional support can be a separate issue later if needed.

### D4. When to expose viewer link

**Background**: How should Discord/Slack show the Web viewer link to the user?

**Options**:

- **A**. Add "View in Web" button to running status embed/control message.
- **B**. Leave link as a context message on RunComplete.
- **C**. Include link in the first thread message.
- **D**. Combine A + C: during execution + at scheduled task start.

**Decision: D**

- The core pain point is not seeing tool call details during execution, so A is required.
- Scheduled tasks can run for a long time, so C is also useful because the first thread message is persistent.
- B creates extra message noise on every run. After completion, users can access sessions from the Web UI session list.
- A's button disappears cleanly when RunComplete deletes the status embed.

### D5. Scope of exposing session type through API

**Background**: Frontend needs information to distinguish the session platform. How much should the API expose?

**Options**:

- **A**. Add only `type` field: `user`, `slack`, `discord`.
- **B**. Add `type` plus platform details such as `external_channel_id`, channel name, etc.

**Decision: A**

- `type` alone is enough to show platform badge and determine read-only mode.
- B has low UX value for its implementation cost; showing channel name has little meaning in Web UI.
- Add one field to `ConversationSessionResponse`: `type: ConversationSessionType`.

### D6. Behavior on broadcast failure

**Background**: What should happen when Discord/Slack adapter succeeds but WebSocket broadcast fails?

**Options**:

- **A**. Best-effort — ignore broadcast failure, with warning log only.
- **B**. Retry — retry broadcast a fixed number of times.
- **C**. Required — treat broadcast failure as failure of the whole event handling.

**Decision: A**

- WebSocket broadcast is an add-on feature. If core delivery to Discord/Slack succeeds, that is sufficient.
- Redis Pub/Sub is fire-and-forget; messages are discarded if there are no subscribers, which is normal.
- If Web UI is not connected, there are zero subscribers rather than a failure.
- B/C over-guarantee this path. Best-effort is enough.

---

## Decision Summary

| Point | Decision | Core Rationale |
|--------|------|----------|
| D1. Dual-publish location | Centrally in dispatch_event() | Single change point, preserves adapter responsibility boundaries |
| D2. Access permission | Own sessions only | Keep existing model and protect privacy |
| D3. Read-only vs bidirectional | Read-only | Matches issue scope and avoids complexity |
| D4. Viewer link exposure | Button during execution + scheduled task start | Solves core pain point with minimal noise |
| D5. Session type exposure | `type` field only | Sufficient information with minimal change |
| D6. Broadcast failure | Best-effort | Add-on feature, fire-and-forget |
