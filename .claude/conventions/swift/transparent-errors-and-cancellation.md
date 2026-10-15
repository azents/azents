---
title: "Propagate Swift failures and cancellation explicitly; do not turn failed work into nil, empty data, or success with try? or catch-all fallbacks."
---

# Transparent Failures and Cancellation

- Use `throws`/`async throws` for failed operations. Catch only where recovery or
  explicit failed UI state belongs; preserve unexpected errors and their cause.
- Do not use `try?`, blanket catches, or `Result` as a success-shaped escape.
  Optional conversion is appropriate only when the contract intentionally treats
  every failure as absence, not as a workaround for handling the error.
- Preserve task cancellation, including SDK-specific cancellation errors.
  Prefer structured child work; unstructured tasks need explicit ownership and
  cancellation. Do not use `Task.detached` to evade isolation/lifecycle design.
- Log an error once at the owning boundary, never with tokens or payload bodies.

## Bad

```swift
let items = (try? await client.items()) ?? []
```

## Good

```swift
func loadItems() async throws -> [Item] {
  try Task.checkCancellation()
  return try await client.items()
}
```

References: [Swift error handling](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/errorhandling/) and [concurrency](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/).
Swift permits optional error conversion; the stricter failure-transparency policy
here follows the repository's Python/global conventions.
