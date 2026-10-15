---
title: "Keep SwiftUI views declarative: pass display values and actions; put networking, persistence, and coordination in feature-owned state."
---

# Declarative SwiftUI Views

- Split a feature into screen composition, feature-owned state/coordination, and
  declarative views receiving values and actions. Do not mandate an extra
  ViewModel for static content or purely local presentation state.
- For observable reference state on the supported iOS baseline, use Observation
  (`@Observable`), `@State` at the owner, and `@Bindable` only where binding is
  needed. Children receive the same owned state rather than constructing copies.
- Keep networking, credentials, persistence, and coordination out of leaf views.
  Attach lifecycle work at the screen boundary and delegate to feature state;
  do not perform side effects while evaluating `body`.

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

Reference: [Apple: Discover Observation](https://developer.apple.com/videos/play/wwdc2023/10149/).
