---
name: typescript-quality-check
description: Run TypeScript format, lint, typecheck, and build checks for Azents TypeScript workspaces.
---

# TypeScript Quality Check

Run from `typescript/`.

```bash
cd /path/to/azents/typescript
pnpm run format
pnpm run lint
pnpm run typecheck
```

For app-specific checks:

```bash
cd /path/to/azents/typescript
pnpm exec turbo run typecheck --filter=@azents/web
pnpm exec turbo run typecheck --filter=@azents/admin-web
```

Run `pnpm run build` when build configuration, Next.js pages, or deployment behavior changes.
