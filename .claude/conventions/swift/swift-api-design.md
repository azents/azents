---
title: "Design Swift APIs for clarity at the call site using Swift naming and access control, rather than translating Python or TypeScript spelling mechanically."
---

# Swift API Design

- Follow Swift API Design Guidelines: meaningful argument labels, role-based
  names, clear side effects, and readable call sites. Prefer clarity over brevity.
- Use Swift predicate names such as `isEmpty`, `hasAccess`, and `canRetry`.
  Python's no-`is_` database-field rule does not transfer to Swift APIs.
- Use access control to hide implementation, not leading-underscore names.
  Keep declarations at the narrowest useful scope; expose `public` deliberately.
- Declare API parameter/result types. Infer obvious local values; do not add
  annotations that merely repeat their initializer.
- Document externally consumed contracts, invariants, errors, and ownership
  with `///` summaries rather than narrating trivial syntax.

References: [Swift API Design Guidelines](https://www.swift.org/documentation/api-design-guidelines/) and [Google Swift Style Guide](https://google.github.io/swift/).
Google is a community style reference, not an Apple requirement; machine layout
remains owned by the repository's selected formatter.
