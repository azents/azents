---
title: "Do not use `getattr`/`setattr`/`object.__setattr__` when type narrowing is missing — narrow, declare, stub, or fake the real type instead."
---

# No getattr/setattr Type Bypass

`getattr` / `setattr` usually appear when the value is still too wide (`object`,
`Any`, an unresolved union) and the code needs a field the checker cannot prove.
That is a typing problem, not a reason to probe attributes dynamically.

**Banned:** using `getattr` / `setattr` / `object.__setattr__` to discover,
default, or invent attributes because the static type is incomplete.

**Do this instead:** narrow with `isinstance` / `match`, declare the field,
add a protocol or typed wrapper, validate at a boundary (`TypeAdapter`, dict
helper), write a `typings/` stub, or use a typed fake in tests.

## Bad

```python
def failure_code(exc: BaseException) -> str | None:
    # Wide type + getattr instead of narrowing or a typed protocol.
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) else None


def attach_http_status(exc: Exception, status_code: int) -> None:
    # Inventing a field the type does not declare.
    setattr(exc, "status_code", status_code)
```

## Good

```python
class ProviderFailure(Protocol):
    code: str | None


def failure_code(exc: BaseException) -> str | None:
    if isinstance(exc, ModelProviderFailure):
        return exc.provider_code
    return None


@dataclass
class HttpStatusError(Exception):
    status_code: int
    message: str
```
