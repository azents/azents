---
title: Configure azents-web Storybook with @storybook/nextjs-vite and shared decorators that mirror Mantine, next-intl, locale, color mode, and app globals.
---

# Storybook Provider Structure

Storybook must render azents-web components in the same styling and locale context as the app.

- ALWAYS use `@storybook/nextjs-vite` for azents-web unless a custom Webpack-only feature is introduced.
- ALWAYS import `@mantine/core/styles.css` and `src/app/globals.css` from `.storybook/preview.tsx`.
- ALWAYS wrap stories with the same app-level UI providers: `AppMantineProvider`, `NextIntlClientProvider`, `LocaleProvider`, and `ColorModeProvider`.
- AVOID adding `TRPCProvider` globally; stories should use static fixtures or per-story mocks instead of live app API calls.

## Bad

```tsx
const preview = {
  decorators: [(Story) => <Story />],
};
```

## Good

```tsx
const preview = {
  globalTypes: {
    colorScheme: {
      toolbar: {
        items: ["light", "dark"],
      },
    },
  },
  decorators: [
    (Story, context) => (
      <StorybookProviders
        colorScheme={resolveColorScheme(context.globals.colorScheme)}
      >
        <Story />
      </StorybookProviders>
    ),
  ],
};
```
