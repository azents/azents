---
title: "Catch only the narrowest exception type that you actually intend to handle — re-raise the rest so unrelated failures stay visible."
---

# Catch the Narrowest Exception Type

A broad `except Exception` that maps every failure to "not found" hides genuine bugs (timeouts, decode errors, auth failures) behind a single fallback path.

- ALWAYS narrow the `except` clause to the specific exception you can actually handle
- If a sub-condition matters (e.g. status code 404), check it explicitly and re-raise everything else

## Bad

```python
try:
    response = await client.get(url)
except Exception:
    return None  # Treats every failure as "not found"
```

## Good

```python
try:
    response = await client.get(url)
    response.raise_for_status()
except httpx.HTTPStatusError as e:
    if e.response.status_code == 404:
        return None
    raise
```
