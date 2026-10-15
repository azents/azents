---
title: "Keep SwiftUI views declarative: pass display values and actions; put networking, persistence, and coordination in feature-owned state."
---

# Declarative SwiftUI Views

- Views describe presentation from explicit inputs and emit user actions.
- Put side effects and coordination in feature-owned state, injected at the
  screen boundary. Keep pure display state local when no side effect is involved.
- Do not start networking, token access, or persistence from a view's `body`.

## Bad

```swift
var body: some View {
  Text(client.loadTitle())
}
```

## Good

```swift
var body: some View {
  Text(title)
}
```
