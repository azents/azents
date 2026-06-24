---
title: "A Python app under `python/apps/` may depend on `python/libs/` packages but NEVER on another app — apps are leaves of the dependency graph; cross-app code goes into a lib."
---

# Apps Depend on Libs Only

`python/apps/foo` importing `python/apps/bar` couples two deployable services and creates surprise breakage on independent deploys. Shared logic belongs in `python/libs/`.

- ALWAYS put shared code in `python/libs/<name>/` and have apps depend on it
- AVOID adding another app's pyproject.toml as a dependency
- libs may depend on other libs (no cycles)

## Bad

```toml
# python/apps/azents/pyproject.toml
dependencies = [
    "azents @ file:///../azents",  # app depending on app
]
```

## Good

```toml
# python/apps/azents/pyproject.toml
dependencies = [
    "az-common @ file:///../../libs/az-common",
]
```
