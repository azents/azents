---
title: "Never use inline `# noqa` suppressions in hand-written Python; fix the lint issue or use a narrowly scoped, documented Ruff configuration exception."
---

# No Inline `noqa` Suppressions

Inline suppressions hide lint findings at the exact point where reviewers need to
understand whether the code is valid.

- NEVER add `# noqa`, with or without diagnostic codes, to hand-written Python source, tests, or stubs.
- Resolve the finding through code structure, naming, typing, imports, or a safer API.
- If a rule is structurally inapplicable to a file category, use the narrowest owning-project Ruff per-file configuration and document why.
- For generated code, change the generator, template, or generation configuration instead of editing generated output.

## Bad

```python
from service import register_plugin  # noqa: F401

assert response.token  # noqa: S101
```

## Good

```python
from service import register_plugin

register_plugin()

if not response.token:
    raise RuntimeError("service response did not include a token")
```
