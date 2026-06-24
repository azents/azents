---
title: "Never disguise an exception as success by stuffing the error into a response object — let it raise so monitoring sees a failure, not a 200 with an error field."
---

# Transparent Error Handling

`{"status": "fail"}` returned from a function that "succeeded" looks like a 200 to every dashboard. The bug stays invisible until a customer complains.

- AVOID returning `{"status": "fail", ...}` / `Output(error=...)` patterns to indicate failure
- ALWAYS raise; let the caller (or top-level exception handler) decide how to surface it

## Bad

```python
async def process(self) -> dict:
    try:
        result = await do_work()
        return {"status": "success", "data": result}
    except Exception:
        return {"status": "fail"}
```

## Good

```python
async def process(self) -> Result:
    return await do_work()
```
