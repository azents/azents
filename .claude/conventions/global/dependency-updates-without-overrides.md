---
title: Update dependencies through package-manager lock resolution and parent dependency upgrades; never add overrides unless the requester explicitly requires one.
---

# Resolve dependency updates without overrides

Dependency overrides hide unresolved constraints and make future graph changes harder to reason about.

- ALWAYS use the package manager's normal lock update first.
- For a blocked transitive dependency, analyze its reverse dependency tree and update the direct or parent dependency that constrains it.
- If no compatible parent update can resolve the target version, stop the update and report the exact dependency path, blocking constraint, and available upstream options.
- NEVER add or retain an override solely to force an update unless the requester explicitly asks for that override.

## Bad

```yaml
overrides:
  vulnerable-package: 2.0.1
```

## Good

```console
$ package-manager why vulnerable-package
$ package-manager update constraining-parent
```
