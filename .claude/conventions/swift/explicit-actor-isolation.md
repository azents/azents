---
title: "Make Swift UI state actor isolation explicit and use Sendable values across concurrency boundaries instead of unchecked isolation escapes."
---

# Explicit Actor Isolation

- Mark feature state that mutates UI as `@MainActor`.
- Cross actor/task boundaries with value types that satisfy `Sendable`.
- Resolve isolation diagnostics at the ownership boundary rather than adding
  `@unchecked Sendable`, `nonisolated(unsafe)`, or detached tasks to silence them.

## Bad

```swift
final class ScreenState: @unchecked Sendable {
  var title = ""
}
```

## Good

```swift
@MainActor
final class ScreenState {
  var title = ""
}
```
