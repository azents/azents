---
title: "Decode external values into validated Codable or domain types at ingress; keep Any dictionaries, casts, and empty-value sentinels out of business logic."
---

# Typed Domain Boundaries

- Decode and validate external input once into operation-specific types.
  `Codable` establishes shape; validate domain invariants explicitly afterward.
- Use declared properties, typed identifiers, and enums instead of
  `[String: Any]`, stringly typed dispatch, or repeated runtime casts.
- Distinguish absent values (`Optional`), valid empty values, and failures.
  Where an existing patch contract distinguishes omission from null, model all
  states explicitly; plain synthesized optional decoding does not preserve both.
- Apply the global ingress rule's explicit unknown-field/extension policy;
  synthesized `Decodable` alone is not an unknown-field rejection mechanism.

## Bad

```swift
let title = payload["title"] as? String ?? ""
```

## Good

```swift
struct ProjectResponse: Decodable {
  let title: String
}
let project = try decoder.decode(ProjectResponse.self, from: data)
```

Reference: [Swift: Encoding and decoding custom types](https://developer.apple.com/documentation/foundation/encoding-and-decoding-custom-types).
