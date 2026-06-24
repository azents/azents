# TypeScript Monorepo Rules

This file covers commands, structure, and workflow for the TypeScript portion of Azents. Coding conventions live in `.claude/rules/typescript-conventions.md` and `.claude/rules/typescript-azents-web-conventions.md`.

Azents uses pnpm workspaces and Turborepo.

## Commands

Run from `typescript/`.

```console
$ pnpm install
$ pnpm run dev
$ pnpm run build
$ pnpm run typecheck
$ pnpm run lint
$ pnpm run format
```

Filtered commands:

```console
$ pnpm run dev --filter=@azents/web
$ pnpm run dev --filter=@azents/admin-web
$ pnpm run generate --filter=@azents/public-client
$ pnpm run generate --filter=@azents/admin-client
```

## Repository Structure

```text
typescript/
├── packages/
│   ├── azents-admin-client/   # Admin API client - generated
│   └── azents-public-client/  # Public API client - generated
└── apps/
    ├── azents-admin-web/      # Admin web app
    └── azents-web/            # Main web app
```

## Code Quality Tools

| Tool | Command | When |
| --- | --- | --- |
| ESLint | `pnpm run lint` | After completing a unit of work |
| Prettier | `pnpm run format` | After completing a unit of work |
| TypeScript | `pnpm run typecheck` | After type or API-client changes |

Do not skip format, lint, or typecheck before completing TypeScript work.

## API Client Generation

- Public client source: `python/apps/azents/specs/public/openapi.json` → `packages/azents-public-client/src/generated/`
- Admin client source: `python/apps/azents/specs/admin/openapi.json` → `packages/azents-admin-client/src/generated/`

Convention: `.claude/conventions/typescript/no-edit-generated.md`.

## Build System

Task dependency chain: `generate` → `build` / `dev` / `typecheck`.
