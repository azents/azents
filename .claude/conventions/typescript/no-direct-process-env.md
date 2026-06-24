---
title: "Never read `process.env.X` directly outside of `src/config/index.ts` — go through `getPublicConfig()` (default, client+server) or `getConfig()` (server-only with private vars)."
---

# Read `process.env` Only in `config/index.ts`

`process.env` access scattered across the codebase makes it impossible to know which env vars exist, which leak to the client bundle, and what the defaults are. The config module is the single source of truth.

- ALWAYS go through `getPublicConfig()` for `NEXT_PUBLIC_*` (works on client and server)
- ALWAYS go through `getConfig()` for server-only secrets
- AVOID `process.env.FOO` anywhere outside `src/config/index.ts`

## Bad

```typescript
// in some component or service file
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost";
```

## Good

```typescript
import { getPublicConfig } from "@/config";

const { apiUrl } = getPublicConfig();
```
