---
title: In patch/partial-update APIs, treat explicit `null` as "set this field to null" — use field omission for "leave unchanged" and separate actions for clearing overrides.
---

# Patch Null Means Set Null

Patch payloads must preserve the distinction between omitted fields and fields explicitly set to `null`.

- ALWAYS treat an explicit `null`/`None` in patch or partial-update input as a request to set that field to null.
- ALWAYS use field omission to mean "leave the current value unchanged".
- AVOID redefining `null` as "remove this override", "use default", or "ignore this field" in a patch API.
- If a domain needs "clear override" semantics distinct from setting null, model it as a separate explicit operation or field.

## Bad

```python
def apply_patch(existing: dict[str, object], patch: dict[str, object | None]) -> dict[str, object]:
    if patch.get("temperature") is None:
        existing.pop("temperature", None)
    return existing
```

## Good

```python
def apply_patch(existing: dict[str, object], patch: dict[str, object | None]) -> dict[str, object | None]:
    if "temperature" in patch:
        existing["temperature"] = patch["temperature"]
    return existing
```
