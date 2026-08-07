---
title: "Do not use `getattr`/`setattr`/`object.__setattr__` to reach or invent attributes the type checker rejects — fix types, stubs, or fakes instead."
---

# No getattr/setattr Type Bypass

Same bar as banning `typing.cast(...)` and bare `type: ignore`: do not dodge the
type checker with dynamic attribute access.

**Banned:** using `getattr` / `setattr` / `object.__setattr__` to read, write, or
invent an attribute that is undeclared on the type, or that ty correctly rejects.

**Do this instead:** declare the field, add a protocol/wrapper, validate through
`TypeAdapter`/dict helpers, write a `typings/` stub, or use a typed fake in tests.

**Allowed exceptions**

- `object.__setattr__` in a frozen dataclass initializer for **already declared** fields
- `monkeypatch.setattr` / `unittest.mock` patching a **real existing** attribute, callable, or module in tests
- One explicit typed boundary for external dynamic payloads (adapter/helper) — not scattered `getattr` probes standing in for a schema

## Bad

```python
error = ResponseError.model_construct(code=code, message=message)
object.__setattr__(error, "status_code", 429)  # field is not on the type
status = getattr(error, "status_code", None)
```

## Good

```python
# Prefer a shape production code already accepts.
status = extract_provider_http_status_code({"error": {"status_code": 429}})

# Or a typed fake/stub with a real field.
class FakeProviderError:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
```
