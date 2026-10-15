---
title: "Inject Swift feature collaborators at composition boundaries instead of using global services; introduce protocols only for a concrete substitution or abstraction need."
---

# Injected Collaborators

- Pass services, storage, configuration, and clocks through initializers or
  functions; assemble concrete dependencies at the app/screen composition root.
- Keep singleton lookups and ambient environment reads out of domain logic.
  SwiftUI environment injection is wiring, not permission to hide dependencies
  in arbitrary helpers.
- Use concrete types by default; use protocols, generics, or closures when
  substitution or a real capability boundary needs them. No protocol-per-class
  or one-use factory layer.

## Bad

```swift
func refresh() async throws {
  items = try await APIClient.shared.items()
}
```

## Good

```swift
init(client: ItemsClient) {
  self.client = client
}
```
