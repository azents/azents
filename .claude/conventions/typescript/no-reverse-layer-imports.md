---
title: "Layer imports flow strictly app → features → shared. `shared/` MUST NOT import from `app/` or `features/`; `features/` MUST NOT import from `app/`."
---

# No Reverse Layer Imports

The dependency direction is fixed: `app/` (pages, layouts) → `features/` (business logic + UI) → `shared/` (providers, theme, utilities). Reverse imports turn the layer model into spaghetti.

- `shared/` may import only from itself or external packages
- `features/` may import from `shared/` and external packages, NOT from `app/` or other features (cross-feature imports go through `shared/`)
- `app/` may import from `features/` and `shared/`

## Bad

```typescript
// shared/lib/color-mode.ts
import { HomeContainer } from "@/features/home/containers/useHomeContainer";  // shared importing feature
```

## Good

```typescript
// features/home/containers/useHomeContainer.ts
import { useColorMode } from "@/shared/lib/color-mode";  // feature importing shared (correct direction)
```
