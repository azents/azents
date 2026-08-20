---
title: "Do not re-export symbols from package `__init__.py` files."
---

# Import From the Defining Module

A re-exporting `__init__.py` hides the source location and can create circular import hazards. An `__init__.py` is also a normal module and may define package-owned symbols directly.

- ALWAYS import a symbol from the module where it is defined.
- AVOID re-exporting a child-module symbol from `__init__.py` to shorten its import path.
- Definitions implemented directly in `__init__.py` are allowed; the package module is their defining module.

## Bad

```python
# foo/__init__.py
from foo.repository import Repository  # re-export

# caller
from foo import Repository
```

## Good

```python
# foo/repository.py
class Repository:
    ...

# caller
from foo.repository import Repository
```

```python
# foo/__init__.py
class PackageRegistry:
    ...

# caller: PackageRegistry is defined by the package module
from foo import PackageRegistry
```
