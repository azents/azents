---
title: "After a successful tRPC mutation, invalidate related queries with `utils.<router>.<query>.invalidate()` — never use `query.refetch()` to refresh data."
---

# tRPC Cache Invalidation, Not `refetch`

`query.refetch()` only refreshes the one place that holds the hook reference. Other components rendering the same data still show stale content. `utils.X.invalidate()` propagates the staleness to every subscriber.

- After Create → invalidate the list query
- After Update → invalidate list AND the single `get` for that ID
- After Delete → invalidate list, the single `get`, AND any related queries
- AVOID `query.refetch()` to refresh after a mutation

## Bad

```tsx
const { data, refetch } = trpc.foods.list.useQuery();
const create = trpc.foods.create.useMutation({
  onSuccess: () => refetch(),
});
```

## Good

```tsx
const utils = trpc.useUtils();

const create = trpc.foods.create.useMutation({
  onSuccess: () => {
    void utils.foods.list.invalidate();
  },
});

const update = trpc.foods.update.useMutation();
update.mutate(input, {
  onSuccess: (response) => {
    void utils.foods.list.invalidate();
    void utils.foods.get.invalidate({ id: response.id });
  },
});
```
