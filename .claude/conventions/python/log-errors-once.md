---
title: "Do not log an exception and then re-raise it — the upstream handler will log it again, producing duplicate stack traces in the aggregator."
---

# Log Errors Only Once

Catch → log → re-raise is the most common cause of duplicate error entries in log aggregation. The convention is: only the boundary that *handles* the exception logs it.

- AVOID `except: logger.error(...); raise`
- If you need to do cleanup but not handle, do cleanup and re-raise without logging
- Top-level handler (FastAPI exception handler, Temporal workflow boundary, CLI entry) is responsible for logging

## Bad

```python
try:
    result = await do_work()
except SomeError as e:
    logger.error(f"Failed: {e}")
    raise
```

## Good

```python
try:
    result = await do_work()
except SomeError:
    cleanup()
    raise
```
