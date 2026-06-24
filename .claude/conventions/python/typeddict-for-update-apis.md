---
title: "Define partial-update / patch payloads as `TypedDict` with `total=False` (or `NotRequired[...]`) so the type system distinguishes \"field omitted\" from \"field set to null\"."
---

# `TypedDict` for Update APIs

Patch endpoints have three states per field: omit (don't change), set to null, set to a value. A regular dataclass conflates the first two.

- ALWAYS model patch / update payloads as `TypedDict(total=False)` or with `NotRequired[...]` per field
- The repository layer can then check `if "field" in payload:` to distinguish omission from explicit null

## Bad

```python
@dataclass
class UpdateUserPayload:
    name: str | None = None
    email: str | None = None  # is None "clear it" or "don't touch it"?
```

## Good

```python
class UpdateUserPayload(TypedDict, total=False):
    name: str
    email: str | None  # explicit None == clear; key absent == leave alone
```
