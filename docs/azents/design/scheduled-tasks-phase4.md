---
title: "Scheduled Tasks Phase 4 — Interface Integration"
design: "../design/scheduled-tasks.md"
tags: [backend, engine]
created: 2026-03-30
updated: 2026-03-30
implemented: 2026-03-30
document_role: supporting
document_type: supporting-phase
migration_source: "docs/azents/design/scheduled-tasks-phase4.md"
---

# Scheduled Tasks Phase 4 — Interface Integration

Design document: [design/scheduled-tasks.md](../design/scheduled-tasks.md)

## Overview

Phase 4 implements broadcasting scheduled task execution result to the **original channel**. Until Phase 3, when scheduler injected message into broker, adapter sent response only inside thread. In Phase 4, on RunComplete, the last text is also sent to channel.

Core rules:
- **Broadcast only on RunComplete** — not on RunStopped
- **Empty text guard** — skip broadcast if `_last_completed_text` is empty
- **No Discord thread link** — do not use `@me` path, only text "See thread for details"
- **Consistent guard logic** — unify Slack/Discord with early return
- **Track Discord broadcast in `_sent_message_ids` too**

## 1. Detect is_scheduled

### 1.1 SchedulerWorker metadata injection

In `_fire_task()` of `worker/scheduler.py`, inject `scheduled_task_id` into `InputMessage.metadata`:

```python
InputMessage(
    text=task.prompt,
    user_id=task.owner_user_id,
    headers=[],
    metadata={"scheduled_task_id": task.id},
    attachments=[],
)
```

### 1.2 Detect in EngineWorker.create_adapter()

In `create_adapter()` of `engine.py`, if first message in `message.messages` has `scheduled_task_id` key in `metadata`, treat as `is_scheduled=True` and pass it when creating adapter:

```python
is_scheduled = any(
    "scheduled_task_id" in m.metadata for m in message.messages
)
```

## 2. SlackAdapter changes

### 2.1 Constructor

Add `is_scheduled: bool` parameter. Add `_last_completed_text: str` buffer field.

### 2.2 TextItem handler

At end of existing TextItem handling, update `_last_completed_text`:

```python
case TextItem(content=text, attachments=atts):
    # ... existing logic ...
    if self._is_scheduled:
        self._last_completed_text = text
```

### 2.3 RunComplete handler

In RunComplete branch, perform broadcast after existing cleanup logic:

```python
case RunComplete():
    # ... existing streamer/control cleanup ...
    await self._broadcast_scheduled_result()

case RunStopped():
    # ... cleanup only, no broadcast ...
```

Handle `RunComplete` and `RunStopped` as separate branches.

### 2.4 _broadcast_scheduled_result()

```python
async def _broadcast_scheduled_result(self) -> None:
    """Broadcast scheduled task result to channel."""
    if not self._is_scheduled:
        return
    if not self._last_completed_text:
        return
    if self._thread_ts is None:
        return
    try:
        await self._client.chat_postMessage(
            channel=self._channel,
            text=self._last_completed_text,
            thread_ts=self._thread_ts,
            reply_broadcast=True,
        )
    except SlackApiError:
        logger.exception(
            "Failed to broadcast scheduled task result to Slack channel",
            extra={"session_id": self._session_id},
        )
```

- `reply_broadcast=True`: Show Slack thread reply in channel too.
- If `thread_ts=None`, already sending directly to channel, so skip.
- Empty text guard prevents meaningless messages.

## 3. DiscordAdapter changes

### 3.1 Constructor

Add `is_scheduled: bool`, `parent_channel_id: str | None` parameters. Add `_last_completed_text: str` buffer field.

`parent_channel_id` is parent channel ID of Discord thread. Used to broadcast scheduled task result executed in thread to parent channel.

### 3.2 TextItem handler

Update `_last_completed_text` at end of existing handling:

```python
case TextItem(content=text, attachments=atts):
    await self._send_text_and_files(text, atts)
    if self._is_scheduled:
        self._last_completed_text = text
```

### 3.3 RunComplete handler

Perform broadcast after existing cleanup logic in RunComplete branch:

```python
case RunComplete():
    self._stop_typing()
    # ... existing status message deletion ...
    await self._broadcast_scheduled_result()

case RunStopped():
    # ... cleanup only, no broadcast ...
```

### 3.4 _broadcast_scheduled_result()

```python
async def _broadcast_scheduled_result(self) -> None:
    """Broadcast scheduled task result to parent channel."""
    if not self._is_scheduled:
        return
    if not self._last_completed_text:
        return
    if self._parent_channel_id is None:
        return
    broadcast_text = (
        self._prefix_agent_name(self._last_completed_text)
        + "\n\n_See thread for details_"
    )
    try:
        msg = await self._client.send_message(
            self._parent_channel_id, broadcast_text
        )
        msg_id = msg.get("id")
        if msg_id is not None:
            self._sent_message_ids.append(str(msg_id))
    except httpx.HTTPStatusError:
        logger.exception(
            "Failed to broadcast scheduled task result to Discord channel",
            extra={"session_id": self._session_id},
        )
```

- Do not use `@me` link — only "See thread for details" text.
- Track broadcast message ID in `_sent_message_ids` too.
- Skip if `parent_channel_id` is None (no parent channel).

## 4. engine.py changes

### 4.1 Detect and pass is_scheduled in create_adapter()

```python
is_scheduled = any(
    "scheduled_task_id" in m.metadata for m in message.messages
)

# Slack
return SlackAdapter(
    ...,
    is_scheduled=is_scheduled,
)

# Discord — pass parent_channel_id
parent_channel_id = (
    ctx.channel_id if ctx.thread_id else None
) if is_scheduled else None
channel_id = ctx.thread_id or ctx.channel_id
return DiscordAdapter(
    ...,
    is_scheduled=is_scheduled,
    parent_channel_id=parent_channel_id,
)
```

For Discord:
- If `ctx.thread_id` exists → running in thread, `parent_channel_id = ctx.channel_id`
- If `ctx.thread_id` absent → running directly in channel, `parent_channel_id = None` (broadcast unnecessary)

## 5. Test Plan

- Verify pyright + ruff pass.
- Verify broadcast occurs only on RunComplete (not RunStopped).
- Verify broadcast skipped when text is empty.
- Verify Discord broadcast message ID is added to `_sent_message_ids`.
