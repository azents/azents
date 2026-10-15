---
title: "Use Swift structs and enums for domain values; use reference types for real identity or shared observation, without speculative inheritance."
---

# Value Semantics First

- Prefer `struct`/`enum` and `let` for DTOs, domain values, identifiers, and
  immutable snapshots; model multiple result fields with a named type.
- Use classes when identity, shared observation, or framework requirements call
  for reference semantics. Make non-extensible classes `final`; do not use
  inheritance as the default reuse mechanism.
- Value semantics do not make a container of mutable references thread-safe.
  Check the members and actual isolation boundary before declaring `Sendable`.

Reference: [Swift: Structures and Classes](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/classesandstructures/).
