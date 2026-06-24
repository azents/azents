---
title: "In async code (especially Temporal workflows/activities) catch asyncio.CancelledError separately and re-raise immediately — putting it under `except Exception` lets shutdown trigger side effects that then replay on retry."
---

# Handle CancelledError Separately

`asyncio.CancelledError` fires on worker shutdown. If your `except Exception` cleanup includes side effects (notifications, writes, external calls), those execute, then the activity replays on retry, executing them again.

- ALWAYS handle `asyncio.CancelledError` in its own `except` clause and re-raise immediately
- Reserve `except Exception` for actual errors that warrant your cleanup side effects

## Bad

```python
try:
    await do_work()
except Exception as e:
    await send_notification()  # Fires on shutdown too — duplicates after replay
    raise
```

## Good

```python
try:
    await do_work()
except asyncio.CancelledError:
    raise
except Exception:
    await send_notification()
    raise
```
