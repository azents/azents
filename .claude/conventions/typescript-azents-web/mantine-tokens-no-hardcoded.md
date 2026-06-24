---
title: "Use Mantine spacing tokens (`\"md\"`, `\"lg\"`) and `rem()` for sizing; use Mantine color CSS variables (`var(--mantine-color-*)`) for colors. Hardcoded `px` values and hex/rgba colors are forbidden in azents-web — exception: feature-card accent radial gradients."
---

# Mantine Tokens Only (No Hardcoded `px` / Hex)

Hardcoded values bypass the design system, so theme changes (dark/light, density) miss those spots. Mantine tokens and CSS variables stay in sync with the theme.

- ALWAYS use Mantine spacing tokens (`"xs"`, `"sm"`, `"md"`, `"lg"`, `"xl"`) or `rem()` for spacing/sizing
- ALWAYS use `var(--mantine-color-*)` or `<Text c="dimmed">` style props for colors
- AVOID hardcoded `px` like `padding: "16px"`
- AVOID hardcoded `#fff` / `rgba(...)` for colors
- Exception: feature-card accent radial gradients (intentional brand identity, not themable)

## Bad

```tsx
<Box style={{ padding: "16px", backgroundColor: "#1a1a1a", color: "rgba(255,255,255,0.7)" }}>
```

## Good

```tsx
<Box p="md" bg="var(--mantine-color-body)">
  <Text c="dimmed">...</Text>
</Box>
```
