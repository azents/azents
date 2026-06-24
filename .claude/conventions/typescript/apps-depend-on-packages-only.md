---
title: "A TypeScript app under `typescript/apps/` may depend on `typescript/packages/` workspaces but NEVER on another app — apps are leaves of the dependency graph."
---

# Apps Depend on Packages Only

Two apps importing each other couples deploys and creates circular workspace deps. Shared logic belongs in `typescript/packages/`.

- ALWAYS put cross-app code in a workspace under `typescript/packages/<name>/`.
- AVOID an `apps/foo/package.json` listing another app as a dependency.
- Packages may depend on other packages, no cycles.

## Bad

```json
// typescript/apps/azents-admin-web/package.json
{
  "dependencies": {
    "@azents/web": "workspace:*"
  }
}
```

## Good

```json
// typescript/apps/azents-admin-web/package.json
{
  "dependencies": {
    "@azents/admin-client": "workspace:*"
  }
}
```
