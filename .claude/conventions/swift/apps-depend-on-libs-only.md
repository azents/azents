---
title: "Swift apps may depend on reusable libraries but not other apps; shared implementation belongs in swift/libs rather than copied app sources."
---

# App and Library Boundaries

- Keep apps as dependency-graph leaves, matching Python/TypeScript workspace
  boundaries. Put actual cross-app Swift reuse under `swift/libs/`.
- Keep app assembly and OS integration in the host; libraries expose typed
  capabilities without reaching back into app targets or UI composition.
- Create a library when reuse exists, not an empty package hierarchy in advance.

## Bad

```text
App B compiles App A's source folder to reuse its service.
```

## Good

```text
App A and App B depend on the same focused Swift library.
```
