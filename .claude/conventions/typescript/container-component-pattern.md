---
title: "Split features into Container hook (state, API, external deps) + Component (pure UI, props in/out only) + Page (createReactContainer entrypoint) — never mix state management into a UI component."
---

# Container / Component / Page Split

The container hook owns trpc/state/external lookups; the component renders props; the page is just the wiring. This split makes UI testable in isolation and makes container logic reviewable independently of styling.

```
features/<feature>/
├── <Feature>Page.tsx        # createReactContainer call
├── types.ts                 # ADT state types
├── schemas.ts               # Zod (forms)
├── containers/
│   └── use<Feature>Container.ts   # state, trpc, useLocalStorage, etc.
└── components/
    └── <Feature>.tsx        # pure UI; no hooks beyond pure transforms
```

- Container (hook): owns `trpc.*`, `useState`, `useLocalStorage`, mutations, derived state
- Component: receives props, renders, calls back via prop callbacks
- `<Feature>Page.tsx`: only `createReactContainer("<Feature>Page", useContainer, Component)`
- `app/.../page.tsx`: imports the Page entry, nothing else

## Bad

```tsx
// FoodList.tsx — UI component reaching into trpc directly
export function FoodList() {
  const { data, isLoading } = trpc.foods.list.useQuery();  // state in UI
  if (isLoading) return <Loader />;
  return <ul>{data?.map((f) => <li key={f.id}>{f.name}</li>)}</ul>;
}
```

## Good

```tsx
// containers/useFoodListContainer.ts
export function useFoodListContainer() {
  const query = trpc.foods.list.useQuery();
  const state: FoodListState = query.isLoading
    ? { type: "LOADING" }
    : { type: "LOADED", foods: query.data ?? [] };
  return { state };
}

// components/FoodList.tsx — pure UI
export function FoodList({ state }: { state: FoodListState }) {
  switch (state.type) {
    case "LOADING": return <Loader />;
    case "LOADED": return <ul>{state.foods.map((f) => <li key={f.id}>{f.name}</li>)}</ul>;
  }
}
```
