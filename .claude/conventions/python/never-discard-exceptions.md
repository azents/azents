---
title: "Never catch a broad Exception and silently discard it (return False, return None, swallow) — let exceptions propagate so the failure surfaces in logs and metrics."
---

# Never Discard Exceptions

A bare `except Exception: return False` turns every error — including bugs, network outages, and credentials problems — into a single uninformative boolean. The caller cannot distinguish "operation failed" from "operation was never attempted."

- AVOID `try: ... except Exception: return False/None/{}` patterns
- ALWAYS let unexpected exceptions propagate; the API layer's exception handler logs and translates them

## Bad

```python
async def stop_workflow(self, workflow_id: str) -> bool:
    try:
        handle = self.temporal.get_workflow_handle(workflow_id)
        await handle.cancel()
        return True
    except Exception:
        return False
```

## Good

```python
async def stop_workflow(self, workflow_id: str) -> None:
    handle = self.temporal.get_workflow_handle(workflow_id)
    await handle.cancel()
```
