---
title: Bind shared structured log fields once with `bind_extra(logger, {...})` when multiple log calls reuse the same context, and pass per-log fields via `extra={...}`.
---

# Bind shared log context once

Use `bind_extra` to attach common structured fields to a logger before a group of related log calls.

- Create `L = bind_extra(logger, {...})` before the first log call that shares that context.
- Call `L.info(...)`, `L.warning(...)`, or `L.exception(...)` for all logs that use the bound fields.
- Pass fields that apply to only one log call with that call's `extra={...}`.
- Use plain `logger.info("...", extra={...})` when there is only one log call.

## Bad

```python
logger.info(
    "Summary started",
    extra={"session_id": session_id, "model": model},
)
logger.warning(
    "Summary fallback used",
    extra={"session_id": session_id, "model": model, "fallback_reason": reason},
)
```

## Good

```python
L = bind_extra(
    logger,
    {
        "session_id": session_id,
        "model": model,
    },
)

L.info("Summary started")
L.warning("Summary fallback used", extra={"fallback_reason": reason})
```
