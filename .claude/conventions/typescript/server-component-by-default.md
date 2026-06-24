---
title: "In Next.js App Router code, default to Server Components — only mark a file `\"use client\"` when it actually needs client-only APIs (state, effects, browser APIs, event handlers)."
---

# Server Component by Default

Every `"use client"` boundary ships JS to the client. Defaulting to Server Components keeps the bundle small and the data flow simple.

- ALWAYS start a new component as a Server Component (no directive)
- Add `"use client"` only when the component truly needs:
  - `useState` / `useEffect` / `useRef`
  - browser APIs (`window`, `document`, `localStorage`)
  - event handlers (`onClick`, `onChange` on real DOM)
  - third-party libs that themselves require client (Mantine UI components inside hooks, etc.)
- Push the `"use client"` boundary as deep as possible — wrap a small leaf, keep the parent server-rendered

## Bad

```tsx
"use client";

export default function PlacePage({ data }: Props) {
  return (
    <div>
      <h1>{data.name}</h1>          {/* purely static */}
      <p>{data.description}</p>      {/* purely static */}
      <CartButton />                 {/* the only thing that needs client */}
    </div>
  );
}
```

## Good

```tsx
// PlacePage.tsx — Server Component (no directive)
export default function PlacePage({ data }: Props) {
  return (
    <div>
      <h1>{data.name}</h1>
      <p>{data.description}</p>
      <CartButton />          {/* this leaf has "use client" */}
    </div>
  );
}
```
