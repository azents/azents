---
title: "Fix Swift ownership and type design before adding casts, type erasure, compiler escapes, or lint suppressions; isolate proven external limitations narrowly."
---

# Improve the Design Before Suppression

1. Correct the state model, value type, generic constraint, actor ownership,
   decoding boundary, or dependency first. Replace the incorrect narrow unit
   rather than layering flags and fallback branches around it.
2. For a demonstrated external SDK limitation, prefer a typed adapter or focused
   wrapper that validates the real contract.
3. Only a documented unavoidable tool/SDK limitation may justify the smallest
   local suppression, with its reason, safety argument, and a focused test.

- Do not add broad `swiftlint:disable`, `@preconcurrency`, unchecked sendability,
  forced casts, or `AnyView` simply to make a diagnostic disappear.
- Deliberate type erasure for an actual heterogeneous API is not a typing fix;
  explain that boundary instead of erasing types across the feature.
- Keep compiler/concurrency warnings as errors; do not lower strictness to
  accommodate newly introduced code.

Reference: [Swift migration guide: incremental adoption](https://www.swift.org/migration/documentation/migrationguide/incrementaladoption/).
