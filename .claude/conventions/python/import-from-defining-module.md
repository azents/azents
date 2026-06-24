---
title: "Import symbols from the module that defines them, not from a re-exporting `__init__.py` — keep `__init__.py` files minimal (docstring only)."
---

# Import From the Defining Module

A re-exporting `__init__.py` makes import paths look short but loses the connection between import statement and source location, and creates circular import hazards as the package grows.

- ALWAYS import from the module that defines the symbol (`from foo.bar.baz import X`)
- Keep `__init__.py` files limited to a module docstring — no re-exports
- AVOID `from foo import X` when `X` actually lives in `foo.bar.baz`

## Bad

```python
# foo/__init__.py
from foo.bar.baz import X  # re-export

# caller
from foo import X
```

## Good

```python
# foo/__init__.py
"""foo 패키지."""

# caller
from foo.bar.baz import X
```
