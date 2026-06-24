---
title: "Never use empty-value placeholders (`\"\"`, `0`, `[]`, `{}`) as defaults to mean \"no value supplied\" — use `None` or keep the parameter required, so \"explicitly set to empty\" is distinguishable from \"not set\"."
---

# No Empty-Value Defaults

`def f(items: list[str] = [])` collapses two distinct cases — caller passed `[]` and caller passed nothing — onto the same code path. The bug only shows up when one of those cases needs a different behavior.

- ALWAYS use `None` to mean "not supplied", or make the parameter required
- AVOID `""`, `0`, `[]`, `{}` as defaults that mean "no value"
- For mutable defaults, the standard `def f(x: list | None = None)` then `x = x or []` pattern still applies

## Bad

```python
def search(query: str = "", limit: int = 0) -> list[Result]: ...
```

## Good

```python
def search(query: str, limit: int | None = None) -> list[Result]: ...
```
