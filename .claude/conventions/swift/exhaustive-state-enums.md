---
title: "Represent mutually exclusive Swift feature states with associated-value enums and exhaustive switches, not independent flags and nullable payloads."
---

# Exhaustive Feature State

- Put each state's required payload in its enum case; make impossible
  loading/error/success combinations unrepresentable.
- Enumerate every case of app-owned closed enums in `switch`. Do not hide a new
  case behind `default`; framework nonfrozen enums may require `@unknown default`.
- Keep transport unknowns at their defined decoding boundary rather than
  inventing successful domain states for them.

## Bad

```swift
var loading = false
var error: String?
var items: [Item]?
```

## Good

```swift
enum ItemsState {
  case loading
  case failed(ItemsFailure)
  case loaded([Item])
}
```

Reference: [Swift: Enumerations](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/enumerations/).
