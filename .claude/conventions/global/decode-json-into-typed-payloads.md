---
title: Decode JSON into an operation- or domain-specific typed payload at ingress instead of using raw JSON primitive unions in business logic.
---

# Decode JSON into typed payloads at ingress

Raw JSON has no domain invariants. Validate it once at the boundary so the rest of the code operates on explicit, type-checked contracts.

- Treat `dict[str, JsonValue]`, `Record<string, unknown>`, and direct `json.loads` results as boundary-only values.
- Decode and validate raw JSON immediately into an operation- or domain-specific Pydantic model, schema-derived type, dataclass, or equivalent typed payload.
- Use a runtime-validating schema for untrusted input. Use a frozen dataclass after explicit validation for simple internal immutable payloads. Use `TypedDict` only when runtime validation has already occurred; it does not validate input by itself.
- Define required, omitted, explicit `null`, default, coercion, and unknown-field behavior in the decoder. Reject unknown fields by default for protocols and tool payloads unless a compatibility contract requires them.
- Pass typed payloads into application and domain code. Access declared fields directly instead of repeating `.get()`, casts, type predicates, or fallback defaults throughout the implementation.
- Convert typed results back to JSON only at the egress boundary.
- A transparent relay may retain opaque JSON only when it neither inspects nor makes decisions from its contents.

## Bad

```python
def execute(payload: dict[str, JsonValue]) -> None:
    path = payload.get("path")
    overwrite = payload.get("overwrite", False)
    # Validation and defaults leak into business logic.
```

## Good

```python
@dataclass(frozen=True)
class WriteRequest:
    path: str
    overwrite: bool


def execute(request: WriteRequest) -> None:
    write_file(request.path, overwrite=request.overwrite)
```
