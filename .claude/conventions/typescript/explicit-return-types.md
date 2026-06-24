---
title: "Functions, especially exported ones and React component props/return values, must declare their return type explicitly — never rely on TypeScript inference for the public API of a function."
---

# Explicit Function Return Types

Inferred return types make refactors silent: change the body, and the contract changes without anyone seeing it in the diff. Explicit types catch the mismatch at the boundary.

- ALWAYS write a return type on exported functions and React components
- Inference is fine for trivial inline arrow functions inside a component body

## Bad

```typescript
export function getUser(id: string) {
  return fetch(`/api/users/${id}`).then((r) => r.json());
}
```

## Good

```typescript
export function getUser(id: string): Promise<User> {
  return fetch(`/api/users/${id}`).then((r) => r.json());
}
```
