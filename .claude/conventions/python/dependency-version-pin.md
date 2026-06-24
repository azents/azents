---
title: "In `python/apps/*` pyproject.toml, pin runtime deps with `==` (exact); in `python/libs/*` pyproject.toml use `>=` (minimum). All dev deps use `>=`. The whole repo runs `lowest-direct` resolution."
---

# Dependency Version Pinning

Apps deploy reproducibly (exact pin); libs are consumed transitively (minimum pin so consumers can satisfy multiple constraints). The repo resolves with `lowest-direct`, so always specify the latest available version.

| Project | Runtime deps | Dev deps |
| --- | --- | --- |
| `python/apps/*` | `==` (exact) | `>=` |
| `python/libs/*` | `>=` (minimum) | `>=` |

- ALWAYS use `uv add <pkg>` from inside the subproject so the lock stays valid
- AVOID `~=`, `^`, or unpinned specs

## Bad

```toml
# python/apps/azents/pyproject.toml
dependencies = [
    "httpx",         # unpinned in an app
    "pydantic ~= 2", # ~= in an app
]
```

## Good

```toml
# python/apps/azents/pyproject.toml
dependencies = [
    "httpx == 0.28.1",
    "pydantic == 2.10.4",
]
```
