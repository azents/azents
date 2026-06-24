---
title: "Use `logger.exception(...)` (or `exc_info=True`) when logging from inside an `except` block so the stack trace is preserved — `f\"...{e}\"` drops the trace and you lose the line that actually raised."
---

# `logger.exception()` Preserves the Trace

Without the stack trace, you have only the exception message and the line of the `except`. With `logger.exception()` you get the entire traceback to the originating frame.

- ALWAYS prefer `logger.exception("static message", extra={...})` inside `except` blocks
- For non-error levels, use `logger.warning("...", exc_info=True, extra={...})`
- AVOID `logger.error(f"... {e}")`

## Bad

```python
except ValueError as e:
    logger.error(f"Validation failed: {e}")
```

## Good

```python
except ValueError:
    logger.exception("Validation failed", extra={"input": input_data})
```
