---
title: "Next.js App Router `page.tsx` files own only data loading, URL/header/cookie reading, redirects, and `generateMetadata` — never render UI directly. The page hands a typed prop bundle to a `<Feature>Page` component under `features/`."
---

# `page.tsx` is a Thin Entrypoint

`page.tsx` is the seam between the framework and our feature code. Mixing UI in there couples the route to its rendering, blocks reuse, and makes every page indirectly depend on the App Router's lifecycle.

What `page.tsx` SHOULD do:
- SSR data load (tRPC server caller, fetch)
- URL params / search params extraction
- HTTP request data (cookies, headers)
- Redirects
- `generateMetadata`

What `page.tsx` SHOULD NOT do:
- Render UI directly (Box, Stack, Typography literals)
- Component design (styling, layout)
- Conditional rendering / component selection

Naming:
- `page.tsx` — route entry, the default export is named `Page`
- `features/<domain>/<Name>Page.tsx` — the actual page UI

## Bad

```tsx
// app/[locale]/place/[slug]/page.tsx
export default function Page() {
  return (
    <Box sx={{ ... }}>
      <Typography>...</Typography>
    </Box>
  );
}
```

## Good

```tsx
// app/[locale]/place/[slug]/page.tsx
import { PlacePage } from "@/features/place/PlacePage";

export async function generateMetadata({ params }) { /* ... */ }

export default async function Page({ params }) {
  const { slug, locale } = await params;
  const data = await trpc.places.getById({ id: slug });
  return <PlacePage data={data} locale={locale} />;
}
```
