---
title: "At async error boundaries, explicitly re-raise asyncio.CancelledError and keep ordinary-error side effects separate from cancellation."
---

# Handle CancelledError Separately

`asyncio.CancelledError` inherits from `BaseException` in supported Python, so
`except Exception` does not catch it. Explicit cancellation branches make shutdown
intent visible and protect it when error boundaries are refactored.

- ALWAYS handle `asyncio.CancelledError` in its own `except` clause and re-raise immediately
- Reserve `except Exception` for actual errors that warrant your cleanup side effects
- Keep required resource cleanup in `finally` or context-manager exit paths.
  Propagating cancellation must not bypass resource ownership.

## Bad

```python
try:
    await do_work()
except BaseException:
    await send_notification()  # Incorrectly treats cancellation as ordinary failure.
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
