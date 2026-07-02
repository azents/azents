---
title: "Never create `index.ts` files in azents-web — the `check-file/no-index` ESLint rule forbids them. Import directly from the file that defines the symbol (`@/features/home/HomePage` not `@/features/home`)."
---

# No `index.ts` Files

`index.ts` re-exports hide the actual file location and create import-cycle hazards. azents-web bans them with `check-file/no-index`; relative imports always go to the defining file.

- ALWAYS import from the defining file: `import { HomePage } from "@/features/home/HomePage"`
- AVOID `import { HomePage } from "@/features/home"`
- AVOID creating `features/<name>/index.ts`

## Bad

```typescript
// features/home/index.ts  ← do not create this
export { HomePage } from "./HomePage";

// app/page.tsx
import { HomePage } from "@/features/home";
```

## Good

```typescript
// app/page.tsx
import { HomePage } from "@/features/home/HomePage";
```
