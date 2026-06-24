---
title: "Avoid `as` type assertions — they bypass type checking. Use generic type parameters, type predicates, or proper narrowing instead."
---

# Avoid `as` Type Assertions

`x as Foo` tells the compiler "trust me, even if you can't see why", which means the next refactor that breaks the assumption compiles cleanly and crashes at runtime.

- AVOID `x as Foo`, especially in `onClick` / `onChange` style callbacks
- Prefer generic type parameters on the consuming API, type guards (`isFoo(x)`), or narrowing via `instanceof` / discriminated unions
- Acceptable: `as const`, `as unknown as Foo` after a guard, well-justified DOM casts

## Bad

```tsx
<DataGrid
  rows={items}
  onRowClick={(params) => setSelectedItem(params.row as ItemType)}
/>
```

## Good

```tsx
<DataGrid<ItemType>
  rows={items}
  onRowClick={(params) => setSelectedItem(params.row)}
/>
```
