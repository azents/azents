---
title: Write normal product UI status copy around user-relevant capability and next actions; separate independently actionable states and reserve implementation metadata for explicit diagnostic surfaces.
---

# User-relevant status copy

Normal product surfaces should help users understand what works, what is affected, and what they can do next.

- ALWAYS present independently actionable concerns as separate states, such as execution availability, service connection, and host-control authority.
- ALWAYS retain selected/configured and applied/effective values when their difference changes a user decision.
- AVOID generations, sequences, digests, internal enum values, raw reason codes, and transport or provider internals in normal UI. Explicit diagnostic or operator surfaces may show them when needed for investigation.

## Bad

```tsx
<Text>Generation 17 · digest a8f3… · provider disconnected</Text>
```

## Good

```tsx
<Status label="Execution environment" value="Ready" />
<Status label="Runtime connection" value="Connected" />
<Status label="Host controls" value="Unavailable" action="Reconnect provider" />
```
