---
title: "Pass variable data via the logger `extra={}` parameter rather than f-string interpolation — structured fields are searchable and indexable in log aggregation."
---

# Structured Logging via `extra={}`

`logger.info(f"Processing {place_id}")` produces a single string the aggregator cannot index. `extra={"place_id": ...}` produces a structured field you can group and filter on.

- ALWAYS pass variable data through `extra={}`, not f-string or `%`-format
- The static message string is the searchable identifier; the dynamic data goes in `extra`

## Bad

```python
logger.info(f"Processing place: {place_id}")
logger.info("Found items: %s", count)
```

## Good

```python
logger.info("Processing place", extra={"place_id": place_id})
logger.info("Found items", extra={"count": count, "category": category})
```
