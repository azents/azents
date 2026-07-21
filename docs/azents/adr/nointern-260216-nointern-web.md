---
title: "nointern-web System Historical Decision Reconstruction"
created: 2026-02-16
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: nointern-260216
historical_reconstruction: true
migration_source: "docs/azents/design/design-system.md"
---

# nointern-web System Historical Decision Reconstruction

- Snapshot: `nointern-260216`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/design-system.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### nointern-260216/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Design Decisions

```typescript
createTheme({
  primaryColor: "gray",
  primaryShade: { light: 9, dark: 0 },
  autoContrast: true,
});
```

- **`primaryColor: "gray"`**: use neutral gray instead of purple/blue.
- **`primaryShade: { light: 9, dark: 0 }`**: near-black buttons in light mode, near-white buttons in dark mode.
- **`autoContrast: true`**: automatically adjust button text color.

### Explicit source section: Color Mode Architecture

Cookie-based color mode management:

```
src/shared/lib/color-mode.ts        — parsing utilities (server/client shared)
src/shared/providers/color-mode.tsx  — Context + Provider (client only)
```

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
