---
title: "Pyright Configuration Review"
tags: [backend, engine, historical-reconstruction]
created: 2026-03-10
updated: 2026-03-10
implemented: 2026-03-10
document_role: primary
document_type: design
snapshot_id: pyright-260310
migration_source: "docs/azents/design/pyright-config.md"
historical_reconstruction: true
---

# Pyright Configuration Review

## Goal

"Strict for our code, pragmatic for libraries"

- Keep `typeCheckingMode = "strict"`.
- Unknown should occur only from libraries without stubs, not from our code (`reportMissingParameterType` and other rules cover our code separately).
- Pyright has no per-library diagnostic suppression feature (confirmed by maintainer erictraut, issue #10566).

## Disabled Rules

| Rule | Value | Reason |
|------|------|------|
| `reportUnknownVariableType` | `"none"` | 100% caused by libraries. Found 0 cases of our code mistakes. |
| `reportUnknownArgumentType` | `"none"` | Downstream propagation of Unknown variables. Since Unknown should not originate from our code, it does not act as a guardrail. |
| `reportUnknownParameterType` | `"none"` | Unknown propagation in callbacks/decorators. Existing cases only disabled entire files with `false`. |
| `reportUnknownMemberType` | `"none"` | Same as other Unknown family. Occurs only in libraries with incomplete internal types even when `py.typed` exists. |
| `reportUnknownLambdaType` | `"none"` | Unknown-family propagation. Cases where lambda parameters are inferred as Unknown. |
| `reportMissingTypeStubs` | `"none"` | Warning for libraries without `py.typed`. Whether to write stubs is judged separately. |
| `reportUnnecessaryIsInstance` | `"none"` | Allow defensive code for fields that libraries such as kubernetes_asyncio declare non-optional but can be None at runtime. |

## Rules Kept Enabled

| Rule | Value | Reason |
|------|------|------|
| `reportUnnecessaryTypeIgnoreComment` | `"error"` | Prevent accumulation of unnecessary `# pyright: ignore`. Automatically detects when library updates improve types. |

## Stub Policy

### Principle

- Write stubs **only when types are defined incorrectly and the corrected type is clear**.
- Stub file must include a comment at the top explaining why it is needed.

### Current Stub

| Package | File | Reason |
|--------|------|------|
| `redis.asyncio` | `typings/redis/asyncio/client.pyi` | async method return type is declared as `Awaitable[T] \| T`, making await impossible (redis-py #3107) |

### Deleted Stubs

Previously there were stubs for 6 libraries (aiodocker, kubernetes_asyncio, litellm, redis, slack_bolt, slack_sdk), but all were deleted:
- All provide their own types with `py.typed` marker.
- Stubs were incorrectly overriding library types and reducing type safety.
- Incomplete type issues are addressed by disabling `reportUnknown*`.

## No TYPE_CHECKING

Because `from __future__ import annotations` is already applied, `TYPE_CHECKING` blocks are unnecessary. Forbid `TYPE_CHECKING` for avoiding circular references; use normal imports consistently.

## Inline Ignore Guide

When using `# pyright: ignore`:
1. Always include specific rule name: `# pyright: ignore[reportArgumentType]`.
2. Add required reason comment: `# kubernetes_asyncio type declaration is inaccurate`.
3. Prefer stub or cast when possible; inline ignore is last resort.

## Implementation Status (2026-04-20)

- ✅ Applied pyright strict mode + disabled Unknown-related rules
- ✅ Reflected in `pyproject.toml` (pyright config block)
- 📍 Current active stub locations: see `python/libs/*/typings/` and app-level `typings/`
