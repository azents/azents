---
name: typescript-dependency-update
description: Update dependencies in the Azents TypeScript workspace.
---

# TypeScript Dependency Update

Run from `typescript/`.

```bash
cd /path/to/azents/typescript
pnpm update <package>
pnpm run format
pnpm run lint
pnpm run typecheck
```

Commit `package.json` and `pnpm-lock.yaml` changes together.
