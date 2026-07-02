# azents-web

Azents AI agent platform web frontend. Next.js 16 App Router + Mantine UI 8.

Coding conventions for this app live in `.claude/rules/typescript-conventions.md`.

## Commands

```console
$ turbo run dev --filter=@azents/web
$ turbo run typecheck --filter=@azents/web
$ turbo run lint --filter=@azents/web
$ turbo run build --filter=@azents/web
```

## Main Technology Stack

- **Framework**: Next.js 16 (App Router)
- **UI**: Mantine 8
- **i18n**: next-intl (cookie-based, no URL routing; unlike azents-web)
- **Data fetching**: tRPC
- **Fonts**: Geist Sans + Geist Mono (`--font-geist-sans`, `--font-geist-mono`)

## Project Structure

```
src/
├── app/                    # Next.js App Router pages
├── features/               # Feature modules
│   └── home/               # Landing page feature
├── shared/
│   ├── lib/                # Utilities such as color mode and locale
│   ├── providers/          # React Context providers
│   └── theme.ts            # Mantine theme settings
└── i18n/                   # next-intl server settings
```

## Color Mode Architecture

The landing page is always dark mode. Do **not** force this in `layout.tsx`; override at page level instead:

```
layout.tsx           → MantineProvider (default theme, no color scheme forced)
  └── page.tsx       → MantineProvider forceColorScheme="dark" (landing only)
  └── dashboard/     → default theme or future user preference
```

Color mode utilities:
- `shared/lib/color-mode.ts` — `parseColorModePreference` (server/client shared)
- `shared/providers/color-mode.tsx` — `ColorModeProvider`
- Cookies: `color-mode-preference` (`light|dark|system`), `color-mode-resolved` (`light|dark`)

## New Feature Workflow

1. Create `features/[name]/`.
2. Define ADT types in `types.ts` when state modeling is needed.
3. Define Zod schemas in `schemas.ts` when forms are present.
4. Add container hooks under `containers/`.
5. Add UI components under `components/`.
6. Add a `[Name]Page.tsx` entry point.
7. Import directly from `app/[name]/page.tsx`; do not use `index.ts` files. See `.claude/conventions/typescript/no-index-files.md`.
