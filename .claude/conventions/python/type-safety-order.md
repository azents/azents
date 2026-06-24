---
title: "Resolve pyright errors by writing well-typed code first, avoiding `typing.cast(...)` and bare ignores; use stubs or reasoned `pyright: ignore[...]` only as a last resort."
---

# Type Safety Resolution Order

`# type: ignore` and `typing.cast(...)` are the wrong first moves. They silence
pyright but offer no signal to anyone reading the code about *why* the type
system is wrong.

1. **Well-typed code first** — narrow with `isinstance`, use generics/protocols, typed wrappers, typed fakes, or validation helpers such as Pydantic `TypeAdapter`. No `hasattr` tricks.
2. **External package issues** — write a stub file in the project's `typings/` directory.
3. **Type-system limitation** — `# pyright: ignore[specificRuleName]  # short reason this can't be expressed in types`

- ALWAYS specify the rule name in the ignore comment (`pyright: ignore[reportUnknownMemberType]`)
- ALWAYS include a short reason after `#`
- AVOID bare `# type: ignore`
- AVOID `typing.cast(...)` in production and test code

## Bad

```python
result = library_call()  # type: ignore

payload = cast(ClientToolResultPayload, event.payload)
assert payload.status == "failed"
```

## Good

```python
# Library returns Any; the actual schema is documented at https://...
result: ResultDict = library_call()  # pyright: ignore[reportUnknownVariableType]

payload = event.payload
assert isinstance(payload, ClientToolResultPayload)
assert payload.status == "failed"
```
